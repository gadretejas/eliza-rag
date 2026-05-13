#!/usr/bin/env python3
"""
Contextualizer — generates document and section contexts for every filing
in chunks.jsonl, enriches all chunks, and writes contextualized_chunks.db
(SQLite).

Contexts are generated in parallel and cached to contexts_cache.json after
each completed call, so interrupted runs can be resumed with --resume.

Usage:
    python3 contextualize.py                        # full run, gpt-5.4-mini
    python3 contextualize.py --resume               # skip already-cached docs
    python3 contextualize.py --workers 10           # parallel workers (default 8)
    python3 contextualize.py --model gpt-5.4        # higher quality
    python3 contextualize.py --model ollama:llama3.2
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

CHUNKS_PATH   = Path("chunks.jsonl")
CACHE_PATH    = Path("contexts_cache.json")
OUTPUT_PATH   = Path("contextualized_chunks.db")

DEFAULT_MODEL   = "gpt-5.4-mini"
DEFAULT_WORKERS = 8
INPUT_CHARS     = 3000

OLLAMA_BASE_URL = "http://localhost:11434/v1"


# ── Prompts ────────────────────────────────────────────────────────────────────

DOCUMENT_PROMPT = """\
You are summarising an SEC EDGAR filing for use in a retrieval system.
Write exactly 2-3 sentences capturing:
  1. The company name, filing type (10-K annual or 10-Q quarterly), and the
     fiscal period covered.
  2. One or two headline financial or strategic facts visible in the excerpt.

Be specific. Include numbers where present. Do not use bullet points or headers.
Write only the summary — no preamble, no label.

Company  : {company} ({ticker})
Filing   : {filing_type}
Filed    : {filing_date}
Period   : {report_period}

Excerpt:
{excerpt}"""

SECTION_PROMPT = """\
You are summarising one section of an SEC EDGAR filing for use in a retrieval
system. Write exactly 2-3 sentences capturing the dominant themes, key facts,
and named entities (companies, regulators, products, metrics) in this section.

This summary will be prepended to every chunk extracted from this section to
improve search retrieval. Be specific and information-dense.

Do not use bullet points or headers. Write only the summary — no preamble,
no label.

Company : {company} ({ticker})
Filing  : {filing_type}, filed {filing_date}
Section : {section_id} — {section_name}

Section text (excerpt):
{excerpt}"""


# ── Task definition ────────────────────────────────────────────────────────────

@dataclass
class ContextTask:
    task_type:    str          # "document" or "section"
    source_file:  str
    section_id:   str | None   # None for document tasks
    prompt:       str
    cache_key:    tuple        # (source_file,) or (source_file, section_id)


# ── LLM client ─────────────────────────────────────────────────────────────────

class LLMClient:
    def __init__(self, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("openai not installed — run: pip install openai")

        if model.startswith("ollama:"):
            self.model    = model[len("ollama:"):]
            self._client  = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                sys.exit("OPENAI_API_KEY not set — add it to .env")
            self.model   = model
            self._client = OpenAI(api_key=api_key)

    def complete(self, prompt: str, retries: int = 2) -> str:
        for attempt in range(retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    temperature=0.2,
                    max_completion_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:
                if attempt < retries:
                    time.sleep(2 ** attempt)   # exponential backoff
                else:
                    print(f"\n  Warning: failed after {retries+1} attempts — {e}",
                          file=sys.stderr)
                    return ""
        return ""


# ── Chunk loading and grouping ─────────────────────────────────────────────────

def load_chunks(path: Path) -> list[dict]:
    chunks = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
    return chunks


def group_chunks(
    chunks: list[dict],
) -> dict[str, dict[str, Any]]:
    """
    Returns {source_file: {"meta": first_chunk, "sections": {section_id: {"meta": ..., "text": ...}}}}
    """
    docs: dict[str, dict] = {}
    for c in chunks:
        sf = c["source_file"]
        if sf not in docs:
            docs[sf] = {"meta": c, "sections": {}}
        sid = c["section_id"]
        if sid not in docs[sf]["sections"]:
            docs[sf]["sections"][sid] = {
                "meta": c,
                "text": "",
            }
        docs[sf]["sections"][sid]["text"] += c["text"] + "\n\n"
    return docs


# ── Task builder ───────────────────────────────────────────────────────────────

def build_tasks(
    docs: dict[str, dict],
    cache: dict,
) -> list[ContextTask]:
    tasks = []

    for sf, doc in docs.items():
        meta = doc["meta"]

        # Document context task
        if sf not in cache or "document_context" not in cache[sf]:
            body_sections = [
                s for sid, s in doc["sections"].items() if sid != "Preamble"
            ]
            excerpt = (body_sections[0]["text"] if body_sections
                       else next(iter(doc["sections"].values()))["text"])
            tasks.append(ContextTask(
                task_type   = "document",
                source_file = sf,
                section_id  = None,
                prompt      = DOCUMENT_PROMPT.format(
                    company      = meta["company"],
                    ticker       = meta["ticker"],
                    filing_type  = meta["filing_type"],
                    filing_date  = meta["filing_date"],
                    report_period= meta.get("report_period", ""),
                    excerpt      = excerpt[:INPUT_CHARS],
                ),
                cache_key = (sf,),
            ))

        # Section context tasks
        cached_sections = cache.get(sf, {}).get("sections", {})
        for sid, sec in doc["sections"].items():
            if sid not in cached_sections:
                sec_meta = sec["meta"]
                tasks.append(ContextTask(
                    task_type   = "section",
                    source_file = sf,
                    section_id  = sid,
                    prompt      = SECTION_PROMPT.format(
                        company      = sec_meta["company"],
                        ticker       = sec_meta["ticker"],
                        filing_type  = sec_meta["filing_type"],
                        filing_date  = sec_meta["filing_date"],
                        section_id   = sid,
                        section_name = sec_meta.get("section_name", ""),
                        excerpt      = sec["text"][:INPUT_CHARS],
                    ),
                    cache_key = (sf, sid),
                ))

    return tasks


# ── Cache helpers ──────────────────────────────────────────────────────────────

def load_cache(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict, path: Path, lock: threading.Lock) -> None:
    with lock:
        path.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                        encoding="utf-8")


def update_cache(
    cache: dict,
    task: ContextTask,
    result: str,
    path: Path,
    lock: threading.Lock,
) -> None:
    with lock:
        sf = task.source_file
        if sf not in cache:
            cache[sf] = {"document_context": "", "sections": {}}
        if task.task_type == "document":
            cache[sf]["document_context"] = result
        else:
            cache[sf]["sections"][task.section_id] = result
        path.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                        encoding="utf-8")


# ── Parallel execution ─────────────────────────────────────────────────────────

def run_parallel(
    tasks: list[ContextTask],
    llm: LLMClient,
    workers: int,
    cache: dict,
    cache_path: Path,
) -> dict:
    if not tasks:
        return cache

    lock        = threading.Lock()
    completed   = 0
    total       = len(tasks)
    start_time  = time.time()

    def execute(task: ContextTask) -> tuple[ContextTask, str]:
        result = llm.complete(task.prompt)
        return task, result

    print(f"Generating {total} contexts with {workers} parallel workers ...")
    print(f"{'─' * 60}")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(execute, task): task for task in tasks}

        for future in as_completed(futures):
            task, result = future.result()
            update_cache(cache, task, result, cache_path, lock)

            with lock:
                completed += 1
                elapsed   = time.time() - start_time
                rate      = completed / elapsed if elapsed > 0 else 0
                remaining = (total - completed) / rate if rate > 0 else 0
                label     = (f"{task.source_file[:30]} / {task.section_id}"
                             if task.task_type == "section"
                             else task.source_file[:40])
                print(
                    f"  [{completed:>4}/{total}]  {label:<45}  "
                    f"ETA {remaining/60:.1f}m",
                    end="\r",
                )

    print()  # newline after \r progress
    return cache


# ── SQLite helpers ─────────────────────────────────────────────────────────────

def init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads during write
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chunks (
            id               TEXT    PRIMARY KEY,
            source_file      TEXT    NOT NULL,
            chunk_index      INTEGER NOT NULL,
            ticker           TEXT    NOT NULL,
            company          TEXT    NOT NULL,
            filing_type      TEXT    NOT NULL,
            filing_date      TEXT    NOT NULL,
            report_period    TEXT,
            quarter          TEXT,
            cik              TEXT,
            section_id       TEXT    NOT NULL,
            section_name     TEXT,
            content_type     TEXT    NOT NULL,
            document_context TEXT,
            section_context  TEXT,
            original_text    TEXT    NOT NULL,
            enriched_text    TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ticker
            ON chunks(ticker);
        CREATE INDEX IF NOT EXISTS idx_section
            ON chunks(section_id);
        CREATE INDEX IF NOT EXISTS idx_filing_date
            ON chunks(filing_date);
        CREATE INDEX IF NOT EXISTS idx_content
            ON chunks(content_type);
        CREATE INDEX IF NOT EXISTS idx_ticker_sec
            ON chunks(ticker, section_id);
        CREATE INDEX IF NOT EXISTS idx_ticker_date
            ON chunks(ticker, filing_date);
    """)
    conn.commit()
    return conn


def write_chunks_to_db(
    conn: sqlite3.Connection,
    chunks: list[dict],
    cache: dict,
) -> tuple[int, int, int]:
    """
    Enrich chunks from cache and upsert into the chunks table.
    Returns (total_written, missing_doc_ctx, missing_sec_ctx).
    """
    missing_doc = 0
    missing_sec = 0
    rows = []

    for c in chunks:
        sf  = c["source_file"]
        sid = c["section_id"]

        doc_ctx = cache.get(sf, {}).get("document_context", "")
        sec_ctx = cache.get(sf, {}).get("sections", {}).get(sid, "")

        if not doc_ctx:
            missing_doc += 1
        if not sec_ctx:
            missing_sec += 1

        parts = []
        if doc_ctx:
            parts.append(f"[DOCUMENT] {doc_ctx}")
        if sec_ctx:
            parts.append(f"[SECTION] {sec_ctx}")
        parts.append(c["text"])
        enriched_text = "\n\n".join(parts)

        rows.append((
            f"{sf}__{c['chunk_index']}",   # id
            sf,
            c["chunk_index"],
            c["ticker"],
            c["company"],
            c["filing_type"],
            c["filing_date"],
            c.get("report_period", ""),
            c.get("quarter", ""),
            c.get("cik", ""),
            sid,
            c.get("section_name", ""),
            c.get("content_type", "text"),
            doc_ctx,
            sec_ctx,
            c["text"],
            enriched_text,
        ))

    conn.executemany("""
        INSERT OR REPLACE INTO chunks (
            id, source_file, chunk_index, ticker, company, filing_type,
            filing_date, report_period, quarter, cik, section_id,
            section_name, content_type, document_context, section_context,
            original_text, enriched_text
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()

    return len(rows), missing_doc, missing_sec


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate contexts for all corpus documents and enrich chunks"
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"LLM model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Parallel workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Ignore existing contexts_cache.json and regenerate everything",
    )
    parser.add_argument(
        "--chunks", type=Path, default=CHUNKS_PATH,
        help=f"Input chunks file (default: {CHUNKS_PATH})",
    )
    parser.add_argument(
        "--cache", type=Path, default=CACHE_PATH,
        help=f"Intermediate cache file (default: {CACHE_PATH})",
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_PATH,
        help=f"Output file (default: {OUTPUT_PATH})",
    )
    args = parser.parse_args()

    if not args.chunks.exists():
        sys.exit(f"{args.chunks} not found — run chunk.py first.")

    print(f"Model   : {args.model}")
    print(f"Workers : {args.workers}")
    print(f"Output  : {args.output}")
    print()

    # ── Load ──────────────────────────────────────────────────────────────────
    print(f"Loading chunks from {args.chunks} ...")
    chunks = load_chunks(args.chunks)
    docs   = group_chunks(chunks)
    print(f"  {len(chunks):,} chunks across {len(docs)} documents")

    cache = {} if args.fresh else load_cache(args.cache)
    if cache:
        print(f"  Resuming — {len(cache)} documents already cached (use --fresh to restart)")
    print()

    # ── Generate contexts ─────────────────────────────────────────────────────
    llm   = LLMClient(args.model)
    tasks = build_tasks(docs, cache)

    if not tasks:
        print("All contexts already cached — skipping generation.")
    else:
        t0    = time.time()
        cache = run_parallel(tasks, llm, args.workers, cache, args.cache)
        elapsed = time.time() - t0
        print(f"\n  {len(tasks)} contexts generated in {elapsed:.0f}s  "
              f"({elapsed/60:.1f} min)")
        print(f"  Cache saved → {args.cache}")
    print()

    # ── Write to SQLite ───────────────────────────────────────────────────────
    print(f"Writing enriched chunks to {args.output} ...")
    conn = init_db(args.output)

    total_written, missing_doc, missing_sec = write_chunks_to_db(conn, chunks, cache)

    if missing_doc:
        print(f"  Warning: {missing_doc} chunks missing document context")
    if missing_sec:
        print(f"  Warning: {missing_sec} chunks missing section context")

    # Token stats from DB
    row = conn.execute("""
        SELECT AVG(LENGTH(original_text) / 4),
               AVG(LENGTH(enriched_text) / 4)
        FROM chunks
    """).fetchone()
    avg_orig, avg_enriched = int(row[0] or 0), int(row[1] or 0)

    # Write meta table
    meta = {
        "total_chunks":        str(total_written),
        "total_documents":     str(len(docs)),
        "model":               llm.model,
        "generated_at":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "avg_original_tokens": str(avg_orig),
        "avg_enriched_tokens": str(avg_enriched),
    }
    conn.executemany(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        meta.items(),
    )
    conn.commit()
    conn.close()

    size_mb = args.output.stat().st_size / 1e6
    print(f"  {total_written:,} chunks written")
    print(f"  Avg original tokens : {avg_orig}")
    print(f"  Avg enriched tokens : {avg_enriched}")
    print(f"  Size                : {size_mb:.0f} MB")
    print(f"  Database            : {args.output}")


if __name__ == "__main__":
    main()
