#!/usr/bin/env python3
"""
Embedding tester — embeds a small sample of chunks into a test ChromaDB
collection and verifies the results before running the full embed.py.

Usage:
    python3 embedding_tester.py                        # 50 chunks, OpenAI
    python3 embedding_tester.py --model local          # free, no API key
    python3 embedding_tester.py --sample 100
    python3 embedding_tester.py --tickers AAPL NVDA    # sample from specific tickers
"""

from __future__ import annotations

import argparse
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from src.config import (
    CONTEXTUALIZED_DB as DB_PATH, TEST_COLLECTION_NAME as TEST_COLLECTION,
    CHROMA_PATH, OPENAI_EMBED_MODEL as OPENAI_MODEL, LOCAL_EMBED_MODEL as LOCAL_MODEL,
)

DEFAULT_SAMPLE   = 50


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_sample(db_path: Path, n: int, tickers: list[str] | None) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    if tickers:
        placeholders = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"SELECT * FROM chunks WHERE ticker IN ({placeholders})",
            tickers,
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM chunks").fetchall()

    conn.close()
    sample = random.sample(list(rows), min(n, len(rows)))
    return [dict(r) for r in sample]


def normalize(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.where(norms == 0, 1.0, norms)


def make_embedder(model_name: str):
    if model_name == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("openai not installed — run: pip install openai")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("OPENAI_API_KEY not set.")
        client = OpenAI(api_key=api_key)

        def embed(texts: list[str]) -> np.ndarray:
            resp = client.embeddings.create(input=texts, model=OPENAI_MODEL)
            return np.array([r.embedding for r in resp.data], dtype=np.float32)

        return embed, OPENAI_MODEL
    else:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            sys.exit("sentence-transformers not installed.")
        model = SentenceTransformer(LOCAL_MODEL)

        def embed(texts: list[str]) -> np.ndarray:
            return model.encode(texts, normalize_embeddings=False,
                                show_progress_bar=False).astype(np.float32)

        return embed, LOCAL_MODEL


def sep(label: str = "") -> None:
    width = 60
    if label:
        print(f"── {label} {'─' * (width - len(label) - 4)}")
    else:
        print("─" * width)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_embedding_shape(vecs: np.ndarray, model_name: str) -> bool:
    expected_dim = 1536 if model_name == "openai" else 384
    ok = vecs.shape[1] == expected_dim
    status = "PASS" if ok else "FAIL"
    print(f"  {'✓' if ok else '✗'}  {status}  Embedding dimension: {vecs.shape[1]} (expected {expected_dim})")
    return ok


def test_normalization(vecs: np.ndarray) -> bool:
    norms = np.linalg.norm(vecs, axis=1)
    ok = bool(np.allclose(norms, 1.0, atol=1e-5))
    status = "PASS" if ok else "FAIL"
    print(f"  {'✓' if ok else '✗'}  {status}  Vectors L2-normalized (norms min={norms.min():.6f} max={norms.max():.6f})")
    return ok


def test_no_zero_vectors(vecs: np.ndarray) -> bool:
    zero_count = int(np.sum(np.all(vecs == 0, axis=1)))
    ok = zero_count == 0
    status = "PASS" if ok else "FAIL"
    print(f"  {'✓' if ok else '✗'}  {status}  No zero vectors ({zero_count} found)")
    return ok


def test_similarity_range(vecs: np.ndarray) -> bool:
    # Dot products of normalized vectors should be in [-1, 1]
    sample = vecs[:10]
    dots = sample @ sample.T
    ok = bool(np.all(dots >= -1.01) and np.all(dots <= 1.01))
    status = "PASS" if ok else "FAIL"
    print(f"  {'✓' if ok else '✗'}  {status}  Similarity scores in [-1, 1] range")
    return ok


def test_chroma_upsert(chunks: list[dict], vecs: np.ndarray, chroma_path: str, model_name: str) -> bool:
    try:
        import chromadb
    except ImportError:
        sys.exit("chromadb not installed — run: pip install chromadb")

    client = chromadb.PersistentClient(path=chroma_path)

    # Clean up any previous test collection
    try:
        client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=TEST_COLLECTION,
        metadata={"hnsw:space": "cosine", "embedding_model": model_name},
    )

    ids       = [c["id"] for c in chunks]
    documents = [c["original_text"] for c in chunks]
    metadatas = [
        {
            "ticker":       c["ticker"],
            "filing_date":  c["filing_date"],
            "section_id":   c["section_id"],
            "content_type": c["content_type"],
            "source_file":  c["source_file"],
            "chunk_index":  int(c["chunk_index"]),
        }
        for c in chunks
    ]

    collection.upsert(ids=ids, embeddings=vecs.tolist(), documents=documents, metadatas=metadatas)

    stored = collection.count()
    ok = stored == len(chunks)
    status = "PASS" if ok else "FAIL"
    print(f"  {'✓' if ok else '✗'}  {status}  ChromaDB upsert: {stored}/{len(chunks)} chunks stored")
    return ok


def test_retrieval(chunks: list[dict], embed_fn, chroma_path: str) -> bool:
    import chromadb

    client     = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_collection(TEST_COLLECTION)

    # Use a random chunk's enriched_text as the query
    query_chunk = random.choice(chunks)
    query_vec   = normalize(embed_fn([query_chunk["enriched_text"]]))[0]

    results = collection.query(
        query_embeddings=[query_vec.tolist()],
        n_results=min(5, len(chunks)),
        include=["documents", "metadatas", "distances"],
    )

    ids       = results["ids"][0]
    distances = results["distances"][0]
    top_id    = ids[0]
    top_dist  = distances[0]
    top_score = 1.0 - top_dist

    # The query chunk itself should be the top result
    self_match = top_id == query_chunk["id"]
    ok = self_match and top_score > 0.95

    status = "PASS" if ok else "WARN"
    symbol = "✓" if ok else "!"
    print(f"  {symbol}  {status}  Self-retrieval: top result = {top_id[:50]}")
    print(f"            query id   = {query_chunk['id'][:50]}")
    print(f"            similarity = {top_score:.4f}  ({'matched' if self_match else 'DID NOT MATCH'})")

    # Show top-5 results
    print(f"\n  Top 5 results for query chunk [{query_chunk['ticker']} · {query_chunk['section_id']}]:")
    for rank, (rid, dist) in enumerate(zip(ids, distances), 1):
        meta  = results["metadatas"][0][rank - 1]
        score = 1.0 - dist
        print(f"    [{rank}] score={score:.4f}  {meta['ticker']} · {meta['section_id']} · {rid[:45]}")

    return ok


def test_cross_query(embed_fn, chroma_path: str) -> bool:
    """Query with a natural language question and check that results make sense."""
    import chromadb

    client     = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_collection(TEST_COLLECTION)

    question  = "What are the primary risk factors?"
    query_vec = normalize(embed_fn([question]))[0]

    results = collection.query(
        query_embeddings=[query_vec.tolist()],
        n_results=min(5, collection.count()),
        include=["metadatas", "distances"],
    )

    metas     = results["metadatas"][0]
    distances = results["distances"][0]

    print(f"\n  NL query: {question!r}")
    for rank, (meta, dist) in enumerate(zip(metas, distances), 1):
        score = 1.0 - dist
        print(f"    [{rank}] score={score:.4f}  {meta['ticker']} · {meta['section_id']}")

    # Just check we got results back with reasonable scores
    ok = len(metas) > 0 and (1.0 - distances[0]) > 0.0
    status = "PASS" if ok else "FAIL"
    print(f"\n  {'✓' if ok else '✗'}  {status}  NL query returned {len(metas)} results")
    return ok


def cleanup(chroma_path: str) -> None:
    try:
        import chromadb
        client = chromadb.PersistentClient(path=chroma_path)
        client.delete_collection(TEST_COLLECTION)
        print(f"\nTest collection '{TEST_COLLECTION}' deleted.")
    except Exception:
        pass


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test embedding pipeline on a small sample before full run"
    )
    parser.add_argument("--model",   choices=["openai", "local"], default="openai")
    parser.add_argument("--sample",  type=int, default=DEFAULT_SAMPLE,
                        help=f"Number of chunks to sample (default: {DEFAULT_SAMPLE})")
    parser.add_argument("--tickers", nargs="+",
                        help="Sample only from these tickers (e.g. AAPL NVDA)")
    parser.add_argument("--path",    default=CHROMA_PATH,
                        help=f"ChromaDB store path (default: {CHROMA_PATH})")
    parser.add_argument("--seed",    type=int, default=42,
                        help="Random seed for reproducible sampling (default: 42)")
    parser.add_argument("--keep",    action="store_true",
                        help="Keep the test collection after the run")
    args = parser.parse_args()

    random.seed(args.seed)

    if not DB_PATH.exists():
        sys.exit(f"{DB_PATH} not found — run contextualize.py first.")

    tickers = [t.upper() for t in args.tickers] if args.tickers else None

    print(f"Model    : {args.model}")
    print(f"Sample   : {args.sample} chunks")
    print(f"Tickers  : {tickers or '(random across all)'}")
    print(f"ChromaDB : {args.path}/")
    print()

    # ── Load sample ────────────────────────────────────────────────────────────
    sep("Loading sample")
    chunks = load_sample(DB_PATH, args.sample, tickers)
    print(f"  Loaded {len(chunks)} chunks")
    tickers_found = sorted({c["ticker"] for c in chunks})
    sections_found = sorted({c["section_id"] for c in chunks})
    print(f"  Tickers  : {tickers_found}")
    print(f"  Sections : {sections_found}")
    print()

    # ── Embed ──────────────────────────────────────────────────────────────────
    sep("Embedding")
    embed_fn, model_label = make_embedder(args.model)

    t0   = time.time()
    texts = [c["enriched_text"] for c in chunks]
    raw_vecs = embed_fn(texts)
    vecs     = normalize(raw_vecs)
    elapsed  = time.time() - t0

    print(f"  Embedded {len(chunks)} chunks in {elapsed:.1f}s  "
          f"({len(chunks)/elapsed:.0f}/s)  shape={vecs.shape}")
    print()

    # ── Vector checks ──────────────────────────────────────────────────────────
    sep("Vector checks")
    results = []
    results.append(test_embedding_shape(vecs, args.model))
    results.append(test_normalization(vecs))
    results.append(test_no_zero_vectors(vecs))
    results.append(test_similarity_range(vecs))
    print()

    # ── ChromaDB checks ────────────────────────────────────────────────────────
    sep("ChromaDB checks")
    results.append(test_chroma_upsert(chunks, vecs, args.path, args.model))
    print()
    results.append(test_retrieval(chunks, embed_fn, args.path))
    print()
    results.append(test_cross_query(embed_fn, args.path))
    print()

    # ── Summary ────────────────────────────────────────────────────────────────
    sep("Result")
    passed = sum(results)
    total  = len(results)
    failed = total - passed
    print(f"  {passed}/{total} checks passed  ({failed} failed/warned)")

    if not args.keep:
        cleanup(args.path)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
