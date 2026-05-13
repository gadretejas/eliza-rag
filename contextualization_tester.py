#!/usr/bin/env python3
"""
Contextualization tester — runs the full document_context + section_context
pipeline on 2 documents and writes enriched chunks to a SQLite database.

Usage:
    python3 contextualization_tester.py
    python3 contextualization_tester.py --tickers MSFT TSLA
    python3 contextualization_tester.py --model ollama:llama3.2
    python3 contextualization_tester.py --output my_test.db
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CHUNKS_PATH     = Path("chunks.jsonl")
DEFAULT_OUT     = Path("contextualization_test_output.db")
DEFAULT_TICKERS = ["AAPL", "NVDA"]

OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL   = "gpt-5.4-mini"

INPUT_CHARS = 3000


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
            self._backend = "ollama"
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                sys.exit("OPENAI_API_KEY not set — add it to .env or export it.")
            self.model    = model
            self._client  = OpenAI(api_key=api_key)
            self._backend = "openai"

    def complete(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            max_completion_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()


# ── Helpers ────────────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    return len(text) // 4


def load_chunks_for_tickers(
    tickers: list[str],
    chunks_path: Path,
) -> dict[str, list[dict]]:
    """Load chunks for the most recent 10-K filing per ticker."""
    by_ticker: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if c["ticker"] in tickers and "10-K" in c["filing_type"]:
                by_ticker[c["ticker"]][c["source_file"]].append(c)

    result: dict[str, list[dict]] = {}
    for ticker in tickers:
        if ticker not in by_ticker:
            print(f"Warning: no 10-K chunks found for {ticker}", file=sys.stderr)
            continue
        latest_file = sorted(by_ticker[ticker].keys())[-1]
        result[latest_file] = by_ticker[ticker][latest_file]

    return result


def build_section_map(chunks: list[dict]) -> dict[str, dict]:
    sections: dict[str, dict] = {}
    for c in chunks:
        sid = c["section_id"]
        if sid not in sections:
            sections[sid] = {
                "section_id":    sid,
                "section_name":  c.get("section_name", ""),
                "ticker":        c["ticker"],
                "company":       c["company"],
                "filing_type":   c["filing_type"],
                "filing_date":   c["filing_date"],
                "report_period": c.get("report_period", ""),
                "text":          "",
            }
        sections[sid]["text"] += c["text"] + "\n\n"
    return sections


# ── Context generation ─────────────────────────────────────────────────────────

def generate_contexts(
    source_file: str,
    chunks: list[dict],
    llm: LLMClient,
) -> tuple[str, dict[str, str]]:
    """
    Generate document_context and per-section section_context.
    Returns (document_context, {section_id: section_context}).
    """
    meta     = chunks[0]
    sections = build_section_map(chunks)

    body_sections = [s for s in sections.values() if s["section_id"] != "Preamble"]
    excerpt_text  = body_sections[0]["text"] if body_sections else chunks[0]["text"]

    print(f"  Generating document context ...", end=" ", flush=True)
    t0 = time.time()
    doc_prompt = DOCUMENT_PROMPT.format(
        company       = meta["company"],
        ticker        = meta["ticker"],
        filing_type   = meta["filing_type"],
        filing_date   = meta["filing_date"],
        report_period = meta.get("report_period", ""),
        excerpt       = excerpt_text[:INPUT_CHARS],
    )
    doc_context = llm.complete(doc_prompt)
    print(f"done ({time.time() - t0:.1f}s)")

    section_contexts: dict[str, str] = {}
    for i, (sid, sec) in enumerate(sections.items(), 1):
        print(
            f"  Section context {i}/{len(sections)}: {sid:<12} ...",
            end=" ", flush=True,
        )
        t0 = time.time()
        sec_prompt = SECTION_PROMPT.format(
            company      = sec["company"],
            ticker       = sec["ticker"],
            filing_type  = sec["filing_type"],
            filing_date  = sec["filing_date"],
            section_id   = sec["section_id"],
            section_name = sec["section_name"],
            excerpt      = sec["text"][:INPUT_CHARS],
        )
        section_contexts[sid] = llm.complete(sec_prompt)
        print(f"done ({time.time() - t0:.1f}s)")

    return doc_context, section_contexts


def enrich_chunks(
    chunks: list[dict],
    doc_context: str,
    section_contexts: dict[str, str],
) -> list[dict]:
    """Build enriched chunk records combining all three layers."""
    enriched = []
    for c in chunks:
        sid         = c["section_id"]
        sec_context = section_contexts.get(sid, "")

        parts = []
        if doc_context:
            parts.append(f"[DOCUMENT] {doc_context}")
        if sec_context:
            parts.append(f"[SECTION] {sec_context}")
        parts.append(c["text"])
        enriched_text = "\n\n".join(parts)

        enriched.append({
            "source_file":      c["source_file"],
            "chunk_index":      c["chunk_index"],
            "ticker":           c["ticker"],
            "company":          c["company"],
            "filing_type":      c["filing_type"],
            "filing_date":      c["filing_date"],
            "report_period":    c.get("report_period", ""),
            "quarter":          c.get("quarter", ""),
            "cik":              c.get("cik", ""),
            "section_id":       sid,
            "section_name":     c.get("section_name", ""),
            "content_type":     c.get("content_type", "text"),
            "document_context": doc_context,
            "section_context":  sec_context,
            "original_text":    c["text"],
            "enriched_text":    enriched_text,
            "original_tokens":  estimate_tokens(c["text"]),
            "enriched_tokens":  estimate_tokens(enriched_text),
        })
    return enriched


# ── SQLite writer ──────────────────────────────────────────────────────────────

def init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
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


def write_to_db(
    conn: sqlite3.Connection,
    enriched_chunks: list[dict],
    meta: dict,
) -> None:
    rows = [
        (
            f"{c['source_file']}__{c['chunk_index']}",
            c["source_file"],
            c["chunk_index"],
            c["ticker"],
            c["company"],
            c["filing_type"],
            c["filing_date"],
            c["report_period"],
            c["quarter"],
            c["cik"],
            c["section_id"],
            c["section_name"],
            c["content_type"],
            c["document_context"],
            c["section_context"],
            c["original_text"],
            c["enriched_text"],
        )
        for c in enriched_chunks
    ]

    conn.executemany("""
        INSERT OR REPLACE INTO chunks (
            id, source_file, chunk_index, ticker, company, filing_type,
            filing_date, report_period, quarter, cik, section_id,
            section_name, content_type, document_context, section_context,
            original_text, enriched_text
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)

    conn.executemany(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        meta.items(),
    )

    conn.commit()


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test contextualization on 2 documents, write to SQLite"
    )
    parser.add_argument(
        "--tickers", nargs=2, default=DEFAULT_TICKERS,
        metavar=("TICKER1", "TICKER2"),
        help=f"Two ticker symbols to test (default: {' '.join(DEFAULT_TICKERS)})",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"LLM model (default: {DEFAULT_MODEL}). Prefix with 'ollama:' for local.",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUT,
        help=f"Output SQLite database (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--chunks", type=Path, default=CHUNKS_PATH,
        help=f"Path to chunks.jsonl (default: {CHUNKS_PATH})",
    )
    args = parser.parse_args()

    if not args.chunks.exists():
        sys.exit(f"{args.chunks} not found — run chunk.py first.")

    tickers = [t.upper() for t in args.tickers]
    print(f"Tickers : {tickers}")
    print(f"Model   : {args.model}")
    print(f"Output  : {args.output}")
    print()

    # ── Load ───────────────────────────────────────────────────────────────────
    print("Loading chunks ...")
    doc_chunks = load_chunks_for_tickers(tickers, args.chunks)
    if not doc_chunks:
        sys.exit("No chunks found for the specified tickers.")

    for sf, chunks in doc_chunks.items():
        sections = {c["section_id"] for c in chunks}
        print(f"  {sf}: {len(chunks)} chunks across {len(sections)} sections")
    print()

    # ── Generate and enrich ────────────────────────────────────────────────────
    llm          = LLMClient(args.model)
    all_enriched: list[dict] = []
    run_start    = time.time()

    for source_file, chunks in doc_chunks.items():
        ticker = chunks[0]["ticker"]
        print(f"── {ticker} ({source_file}) ──────────────────────────────────────")
        doc_ctx, sec_ctxs = generate_contexts(source_file, chunks, llm)
        enriched = enrich_chunks(chunks, doc_ctx, sec_ctxs)
        all_enriched.extend(enriched)
        print()

    total_elapsed = time.time() - run_start

    # ── Stats ──────────────────────────────────────────────────────────────────
    orig_tokens     = sum(c["original_tokens"] for c in all_enriched)
    enriched_tokens = sum(c["enriched_tokens"] for c in all_enriched)
    avg_orig        = orig_tokens / len(all_enriched)
    avg_enriched    = enriched_tokens / len(all_enriched)

    print("── Summary ───────────────────────────────────────────────────────────")
    print(f"  Documents processed : {len(doc_chunks)}")
    print(f"  Total chunks        : {len(all_enriched)}")
    print(f"  Avg original tokens : {avg_orig:.0f}")
    print(f"  Avg enriched tokens : {avg_enriched:.0f}  "
          f"(+{avg_enriched - avg_orig:.0f}, "
          f"+{(avg_enriched/avg_orig - 1)*100:.0f}%)")
    print(f"  Total time          : {total_elapsed:.1f}s")
    print()

    # ── Write to SQLite ────────────────────────────────────────────────────────
    from datetime import datetime, timezone
    meta_record = {
        "generated_at":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model":               llm.model,
        "tickers":             ",".join(tickers),
        "total_chunks":        str(len(all_enriched)),
        "total_documents":     str(len(doc_chunks)),
        "avg_original_tokens": str(round(avg_orig)),
        "avg_enriched_tokens": str(round(avg_enriched)),
    }

    conn = init_db(args.output)
    write_to_db(conn, all_enriched, meta_record)
    conn.close()

    size_kb = args.output.stat().st_size / 1_000
    print(f"Database written → {args.output}  ({size_kb:.0f} KB)")
    print(f"  Rows in chunks table : {len(all_enriched)}")
    print()
    print(f"Inspect with:")
    print(f"  python3 query_db.py --db {args.output} --summary")
    print(f"  python3 query_db.py --db {args.output} --ticker {tickers[0]}")


if __name__ == "__main__":
    main()
