#!/usr/bin/env python3
"""
Build the ChromaDB vector collection from contextualized_chunks.db.
Falls back to chunks.jsonl (raw text) if the DB is not present.
Run once after contextualize.py.

Usage:
    python embed.py                        # OpenAI text-embedding-3-small
    python embed.py --model local          # local all-MiniLM-L6-v2, free
    python embed.py --reset                # delete collection and rebuild from scratch
    python embed.py --workers 10           # parallel embedding workers (default: 5)
    python embed.py --path ./chroma_store  # custom store location
"""

import argparse
import json
import logging
import os
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

DB_PATH         = Path("contextualized_chunks.db")
CHUNKS_PATH     = Path("chunks.jsonl")
CHROMA_PATH     = "chroma_store"
COLLECTION_NAME = "sec_filings"

OPENAI_MODEL = "text-embedding-3-small"
LOCAL_MODEL  = "all-MiniLM-L6-v2"

MAX_RETRIES  = 6
BACKOFF_BASE = 1.0
BACKOFF_MAX  = 64.0


# ── Logging ────────────────────────────────────────────────────────────────────

def setup_logging(log_path: str) -> logging.Logger:
    log = logging.getLogger("embed")
    log.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%H:%M:%S")

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    log.addHandler(ch)
    log.addHandler(fh)
    return log


# ── Chunk loading ──────────────────────────────────────────────────────────────

def load_from_db(path: Path) -> list[dict]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM chunks ORDER BY source_file, section_id, chunk_index"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_from_jsonl(path: Path) -> list[dict]:
    chunks = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
    return chunks


# ── Embedding helpers ──────────────────────────────────────────────────────────

def _normalize(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vecs / norms


def _embed_openai(texts: list[str], model: str, client) -> np.ndarray:
    resp = client.embeddings.create(input=texts, model=model)
    return np.array([r.embedding for r in resp.data], dtype=np.float32)


def _embed_local(texts: list[str], st_model) -> np.ndarray:
    return st_model.encode(
        texts,
        normalize_embeddings=False,
        show_progress_bar=False,
        batch_size=64,
    ).astype(np.float32)


def embed_with_backoff(
    embed_fn,
    texts: list[str],
    batch_num: int,
    log: logging.Logger,
) -> np.ndarray:
    """Call embed_fn with exponential backoff on transient errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return embed_fn(texts)
        except Exception as exc:
            # Detect rate-limit vs hard failure
            is_rate_limit = "rate" in str(exc).lower() or "429" in str(exc)
            if attempt == MAX_RETRIES - 1:
                log.error(
                    "Batch %d failed after %d attempts: %s",
                    batch_num, MAX_RETRIES, exc,
                )
                raise

            wait = min(BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1.0),
                       BACKOFF_MAX)
            level = logging.WARNING if is_rate_limit else logging.ERROR
            log.log(
                level,
                "Batch %d attempt %d/%d — %s: %s  (retry in %.1fs)",
                batch_num, attempt + 1, MAX_RETRIES,
                "rate limited" if is_rate_limit else "error",
                exc,
                wait,
            )
            time.sleep(wait)


# ── Per-batch worker ───────────────────────────────────────────────────────────

def process_batch(
    batch_num: int,
    batch: list[dict],
    embed_field: str,
    doc_field: str,
    embed_fn,
    collection,
    upsert_lock: threading.Lock,
    counter: dict,
    counter_lock: threading.Lock,
    n_total: int,
    start_time: float,
    log: logging.Logger,
) -> int:
    """Embed one batch and upsert into ChromaDB. Returns number of chunks upserted."""
    embed_texts = [c[embed_field] for c in batch]
    doc_texts   = [c[doc_field]   for c in batch]

    log.debug("Batch %d  embedding %d chunks", batch_num, len(batch))
    vecs = _normalize(embed_with_backoff(embed_fn, embed_texts, batch_num, log))

    ids       = [c["id"] for c in batch]
    metadatas = [
        {
            "source_file":   c["source_file"],
            "chunk_index":   int(c["chunk_index"]),
            "ticker":        c["ticker"],
            "company":       c["company"],
            "filing_type":   c["filing_type"],
            "filing_date":   c["filing_date"],
            "report_period": c.get("report_period") or "",
            "quarter":       c.get("quarter") or "",
            "cik":           c.get("cik") or "",
            "section_id":    c["section_id"],
            "section_name":  c.get("section_name") or "",
            "content_type":  c.get("content_type") or "text",
        }
        for c in batch
    ]

    with upsert_lock:
        collection.upsert(
            ids=ids,
            embeddings=vecs.tolist(),
            documents=doc_texts,
            metadatas=metadatas,
        )
    log.debug("Batch %d  upserted %d chunks", batch_num, len(batch))

    with counter_lock:
        counter["done"] += len(batch)
        done = counter["done"]

    elapsed  = time.time() - start_time
    rate     = done / elapsed if elapsed > 0 else 0
    eta_secs = (n_total - done) / rate if rate > 0 else 0
    eta_str  = f"{int(eta_secs // 60)}m{int(eta_secs % 60):02d}s"

    log.info(
        "Progress  %d/%d chunks  (%.0f/s)  ETA %s",
        done, n_total, rate, eta_str,
    )

    return len(batch)


# ── Collection builder ─────────────────────────────────────────────────────────

def build_collection(
    model_name: str,
    batch_size: int,
    workers: int,
    chroma_path: str,
    collection_name: str,
    reset: bool,
    db_path: Path,
    chunks_path: Path,
    log: logging.Logger,
) -> None:
    try:
        import chromadb
    except ImportError:
        sys.exit("chromadb not installed — run: pip install chromadb")

    # ── Connect ────────────────────────────────────────────────────────────────
    client = chromadb.PersistentClient(path=chroma_path)
    log.info("ChromaDB : %s/", chroma_path)

    if reset:
        try:
            client.delete_collection(collection_name)
            log.info("Deleted existing collection '%s'", collection_name)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={
            "hnsw:space":      "cosine",
            "embedding_model": model_name,
        },
    )
    existing = collection.count()
    log.info("Collection : %s  (existing: %d vectors)", collection_name, existing)

    # ── Load chunks ────────────────────────────────────────────────────────────
    if db_path.exists():
        log.info("Loading enriched chunks from %s ...", db_path)
        chunks = load_from_db(db_path)
        embed_field = "enriched_text"
        doc_field   = "original_text"
        log.info("  %d chunks  (embedding enriched_text, storing original_text)", len(chunks))
    else:
        log.warning("%s not found — falling back to %s", db_path, chunks_path)
        if not chunks_path.exists():
            sys.exit(f"{chunks_path} not found — run chunk.py first.")
        chunks = load_from_jsonl(chunks_path)
        embed_field = "text"
        doc_field   = "text"
        log.info("  %d chunks  (raw text — run contextualize.py for enriched embeddings)", len(chunks))

    # Skip already-embedded chunks (resume support)
    if existing > 0 and not reset:
        embedded_ids = set(
            collection.get(include=[])["ids"]
        )
        before = len(chunks)
        chunks = [c for c in chunks if c["id"] not in embedded_ids]
        log.info(
            "Resuming: skipping %d already-embedded chunks, %d remaining",
            before - len(chunks), len(chunks),
        )

    if not chunks:
        log.info("Nothing to embed — collection is already up to date.")
        log.info("Vectors : %d", collection.count())
        return

    # ── Set up embedding function ──────────────────────────────────────────────
    if model_name == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("openai not installed — run: pip install openai")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("OPENAI_API_KEY not set — add it to .env or export it.")
        oa_client = OpenAI(api_key=api_key)
        embed_fn  = lambda batch: _embed_openai(batch, OPENAI_MODEL, oa_client)
        log.info("Model    : OpenAI %s  |  workers=%d", OPENAI_MODEL, workers)
    else:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            sys.exit("sentence-transformers not installed — run: pip install sentence-transformers")
        st_model = SentenceTransformer(LOCAL_MODEL)
        embed_fn = lambda batch: _embed_local(batch, st_model)
        log.info("Model    : local %s  |  workers=%d", LOCAL_MODEL, workers)

    # ── Prepare batches ────────────────────────────────────────────────────────
    batches = [
        chunks[i : i + batch_size]
        for i in range(0, len(chunks), batch_size)
    ]
    n_total    = len(chunks)
    n_batches  = len(batches)
    upsert_lock  = threading.Lock()
    counter      = {"done": 0}
    counter_lock = threading.Lock()
    start_time   = time.time()

    log.info(
        "Embedding %d chunks in %d batches (batch_size=%d, workers=%d)",
        n_total, n_batches, batch_size, workers,
    )

    # ── Parallel embed + upsert ────────────────────────────────────────────────
    failed_batches: list[int] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                process_batch,
                batch_num=i + 1,
                batch=batch,
                embed_field=embed_field,
                doc_field=doc_field,
                embed_fn=embed_fn,
                collection=collection,
                upsert_lock=upsert_lock,
                counter=counter,
                counter_lock=counter_lock,
                n_total=n_total,
                start_time=start_time,
                log=log,
            ): i + 1
            for i, batch in enumerate(batches)
        }

        for future in as_completed(futures):
            batch_num = futures[future]
            try:
                future.result()
            except Exception as exc:
                log.error("Batch %d failed permanently: %s", batch_num, exc)
                failed_batches.append(batch_num)

    # ── Summary ────────────────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    final   = collection.count()

    log.info("─" * 50)
    log.info("Collection '%s' ready", collection_name)
    log.info("Vectors    : %d", final)
    log.info("Time       : %.0fs  (%.0f chunks/s)", elapsed, n_total / elapsed if elapsed else 0)

    if failed_batches:
        log.warning(
            "%d batch(es) failed permanently: %s  — re-run embed.py to retry",
            len(failed_batches), failed_batches,
        )
    else:
        log.info("All batches succeeded.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build ChromaDB collection from contextualized_chunks.db"
    )
    parser.add_argument(
        "--model", choices=["openai", "local"], default="openai",
        help="Embedding model (default: openai)",
    )
    parser.add_argument("--batch-size", type=int, default=200,
                        help="Chunks per API call (default: 200)")
    parser.add_argument("--workers",    type=int, default=5,
                        help="Parallel embedding workers (default: 5)")
    parser.add_argument("--path",       default=CHROMA_PATH,
                        help=f"ChromaDB persistent store path (default: {CHROMA_PATH})")
    parser.add_argument("--collection", default=COLLECTION_NAME,
                        help=f"Collection name (default: {COLLECTION_NAME})")
    parser.add_argument("--reset",      action="store_true",
                        help="Delete and recreate the collection before embedding")
    parser.add_argument("--db",         type=Path, default=DB_PATH,
                        help=f"SQLite DB path (default: {DB_PATH})")
    parser.add_argument("--chunks",     type=Path, default=CHUNKS_PATH,
                        help=f"Fallback chunks.jsonl (default: {CHUNKS_PATH})")
    parser.add_argument("--log",        default="embed.log",
                        help="Log file path (default: embed.log)")
    args = parser.parse_args()

    log = setup_logging(args.log)
    log.info("=" * 50)
    log.info("embed.py started")

    build_collection(
        model_name      = args.model,
        batch_size      = args.batch_size,
        workers         = args.workers,
        chroma_path     = args.path,
        collection_name = args.collection,
        reset           = args.reset,
        db_path         = args.db,
        chunks_path     = args.chunks,
        log             = log,
    )


if __name__ == "__main__":
    main()
