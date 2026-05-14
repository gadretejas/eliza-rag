#!/usr/bin/env python3
"""
Build the ChromaDB vector collection from contextualized_chunks.db.
Falls back to chunks.jsonl (raw text) if the DB is not present.
Run once after contextualize.py.

Usage:
    python embed.py                       # OpenAI text-embedding-3-small
    python embed.py --model local         # local all-MiniLM-L6-v2, free
    python embed.py --reset               # delete collection and rebuild from scratch
    python embed.py --path ./chroma_store # custom store location
"""

import argparse
import json
import os
import sqlite3
import sys
import time
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


# ── Collection builder ─────────────────────────────────────────────────────────

def build_collection(
    model_name: str,
    batch_size: int,
    chroma_path: str,
    collection_name: str,
    reset: bool,
    db_path: Path,
    chunks_path: Path,
) -> None:
    try:
        import chromadb
    except ImportError:
        sys.exit("chromadb not installed — run: pip install chromadb")

    # ── Connect ────────────────────────────────────────────────────────────────
    client = chromadb.PersistentClient(path=chroma_path)
    print(f"ChromaDB   : {chroma_path}/")

    if reset:
        try:
            client.delete_collection(collection_name)
            print(f"Deleted existing collection '{collection_name}'")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={
            "hnsw:space":      "cosine",
            "embedding_model": model_name,
        },
    )
    print(f"Collection : {collection_name}  (existing: {collection.count():,} vectors)")

    # ── Load chunks ────────────────────────────────────────────────────────────
    if db_path.exists():
        print(f"Loading enriched chunks from {db_path} ...")
        chunks = load_from_db(db_path)
        embed_field = "enriched_text"
        doc_field   = "original_text"
        print(f"  {len(chunks):,} chunks  (embedding enriched_text, storing original_text)")
    else:
        print(f"Warning: {db_path} not found — falling back to {chunks_path}")
        if not chunks_path.exists():
            sys.exit(f"{chunks_path} not found — run chunk.py first.")
        chunks = load_from_jsonl(chunks_path)
        embed_field = "text"
        doc_field   = "text"
        print(f"  {len(chunks):,} chunks  (raw text — run contextualize.py for enriched embeddings)")

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
        print(f"Model      : OpenAI {OPENAI_MODEL}")
    else:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            sys.exit("sentence-transformers not installed — run: pip install sentence-transformers")
        st_model = SentenceTransformer(LOCAL_MODEL)
        embed_fn = lambda batch: _embed_local(batch, st_model)
        print(f"Model      : local {LOCAL_MODEL}")

    # ── Embed and upsert in batches ────────────────────────────────────────────
    n           = len(chunks)
    n_batches   = (n + batch_size - 1) // batch_size
    total_start = time.time()

    for batch_num, i in enumerate(range(0, n, batch_size), start=1):
        batch = chunks[i : i + batch_size]

        embed_texts = [c[embed_field] for c in batch]
        doc_texts   = [c[doc_field]   for c in batch]

        print(
            f"  Batch {batch_num:>4}/{n_batches}  "
            f"({i:>6}–{min(i + batch_size, n):<6})  "
            f"[{time.time() - total_start:.0f}s]",
            end="\r",
        )

        vecs = _normalize(embed_fn(embed_texts))

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

        collection.upsert(
            ids=ids,
            embeddings=vecs.tolist(),
            documents=doc_texts,
            metadatas=metadatas,
        )

        if model_name == "openai":
            time.sleep(0.05)

    print()
    elapsed = time.time() - total_start
    print(f"\nCollection '{collection_name}' ready")
    print(f"Vectors    : {collection.count():,}")
    print(f"Time       : {elapsed:.0f}s")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build ChromaDB collection from contextualized_chunks.db"
    )
    parser.add_argument(
        "--model", choices=["openai", "local"], default="openai",
        help="Embedding model (default: openai)",
    )
    parser.add_argument("--batch-size",  type=int, default=200)
    parser.add_argument("--path",        default=CHROMA_PATH,
                        help=f"ChromaDB persistent store path (default: {CHROMA_PATH})")
    parser.add_argument("--collection",  default=COLLECTION_NAME,
                        help=f"Collection name (default: {COLLECTION_NAME})")
    parser.add_argument("--reset",       action="store_true",
                        help="Delete and recreate the collection before embedding")
    parser.add_argument("--db",          type=Path, default=DB_PATH,
                        help=f"SQLite DB path (default: {DB_PATH})")
    parser.add_argument("--chunks",      type=Path, default=CHUNKS_PATH,
                        help=f"Fallback chunks.jsonl (default: {CHUNKS_PATH})")
    args = parser.parse_args()

    build_collection(
        model_name      = args.model,
        batch_size      = args.batch_size,
        chroma_path     = args.path,
        collection_name = args.collection,
        reset           = args.reset,
        db_path         = args.db,
        chunks_path     = args.chunks,
    )


if __name__ == "__main__":
    main()
