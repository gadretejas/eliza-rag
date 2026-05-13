#!/usr/bin/env python3
"""
Build the FAISS vector index from chunks.jsonl.
Run once after chunk.py; outputs index.faiss.

Usage:
    python embed.py                      # OpenAI text-embedding-3-small (needs OPENAI_API_KEY)
    python embed.py --model local        # local all-MiniLM-L6-v2, no API key needed
    python embed.py --batch-size 100     # override batch size
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

CHUNKS_PATH = Path("chunks.jsonl")
INDEX_PATH  = Path("index.faiss")

OPENAI_MODEL = "text-embedding-3-small"
OPENAI_DIM   = 1536
LOCAL_MODEL  = "all-MiniLM-L6-v2"
LOCAL_DIM    = 384


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


def build_index(
    chunks_path: Path,
    index_path: Path,
    model_name: str,
    batch_size: int,
) -> None:
    try:
        import faiss
    except ImportError:
        sys.exit("faiss-cpu not installed. Run: pip install faiss-cpu")

    print(f"Loading chunks from {chunks_path} ...")
    chunks = []
    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
    n = len(chunks)
    print(f"  {n:,} chunks")

    texts = [c["text"] for c in chunks]

    # ── Set up embedding function ──────────────────────────────────────────────
    if model_name == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("openai not installed. Run: pip install openai")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit("OPENAI_API_KEY environment variable not set.")
        client  = OpenAI(api_key=api_key)
        embed_fn = lambda batch: _embed_openai(batch, OPENAI_MODEL, client)
        dim      = OPENAI_DIM
        print(f"Model : OpenAI {OPENAI_MODEL}  (dim={dim})")
    else:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            sys.exit("sentence-transformers not installed. Run: pip install sentence-transformers")
        st_model = SentenceTransformer(LOCAL_MODEL)
        embed_fn = lambda batch: _embed_local(batch, st_model)
        dim      = LOCAL_DIM
        print(f"Model : local {LOCAL_MODEL}  (dim={dim})")

    # ── Embed in batches ───────────────────────────────────────────────────────
    index       = faiss.IndexFlatIP(dim)   # cosine sim after L2 normalisation
    n_batches   = (n + batch_size - 1) // batch_size
    total_start = time.time()

    for batch_num, i in enumerate(range(0, n, batch_size), start=1):
        batch = texts[i : i + batch_size]
        print(
            f"  Batch {batch_num:>4}/{n_batches}  "
            f"({i:>6}–{min(i + batch_size, n):<6})  "
            f"[{time.time() - total_start:.0f}s]",
            end="\r",
        )
        vecs = embed_fn(batch)
        vecs = _normalize(vecs)
        index.add(vecs)

        if model_name == "openai":
            time.sleep(0.05)   # stay within rate limits

    print()
    elapsed = time.time() - total_start
    faiss.write_index(index, str(index_path))

    size_mb = index_path.stat().st_size / 1e6
    print(f"\nIndex saved → {index_path}  ({size_mb:.0f} MB)")
    print(f"Vectors : {index.ntotal:,}")
    print(f"Time    : {elapsed:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FAISS index from chunks.jsonl")
    parser.add_argument(
        "--model",
        choices=["openai", "local"],
        default="openai",
        help="Embedding model (default: openai)",
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--chunks",     type=Path, default=CHUNKS_PATH)
    parser.add_argument("--output",     type=Path, default=INDEX_PATH)
    args = parser.parse_args()

    if not args.chunks.exists():
        sys.exit(f"{args.chunks} not found — run chunk.py first.")

    build_index(args.chunks, args.output, args.model, args.batch_size)


if __name__ == "__main__":
    main()
