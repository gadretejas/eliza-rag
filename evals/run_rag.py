#!/usr/bin/env python3
"""
Stage 2 — RAG answer generation.

Reads evals/data/synthetic_test_set.jsonl, sends each question to the RAG
system, and writes evals/data/rag_outputs.jsonl.

Retrieval runs sequentially (single ChromaDB client to avoid concurrent
SQLite access). LLM calls run in parallel across a thread pool.

Usage:
    python -m evals.run_rag
    python -m evals.run_rag --workers 6
    python -m evals.run_rag --model gpt-5.4-mini --top-k 15
    python -m evals.run_rag --input evals/data/synthetic_test_set.jsonl
    python -m evals.run_rag --limit 20   # useful for spot-checks
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.answer.answer import (
    AnswerConfig, LLMClient,
    build_prompt, parse_citations, load_system_prompt,
)
from src.retrieval.retrieve import HybridRetriever, RetrieverConfig

DATA_DIR = Path(__file__).parent / "data"

_FALLBACK = (
    "The available filings do not contain enough information to answer this question."
)

# ── Comparative retrieval diversity ───────────────────────────────────────────

_COMPARATIVE_SIGNALS = (
    "compare", "comparing", "contrast", "both filings", "both reports",
    "versus", " vs ", "vs.", "differ", "how did", "between the",
    "across the", "in each", "in both",
)


def _is_comparative(item: dict) -> bool:
    """Return True if this question requires chunks from multiple source filings."""
    if item.get("question_type") == "comparative":
        return True
    q = item.get("question", "").lower()
    return any(sig in q for sig in _COMPARATIVE_SIGNALS)


def _diverse_retrieve(
    retriever,
    wide_retriever,
    question: str,
    top_k: int,
) -> list[dict]:
    """
    Source-aware retrieval for comparative questions.

    Fetches top_k chunks normally. If all chunks come from a single source
    file, falls back to a wider fetch (top_k * 3) and rebalances so that the
    two best-matching source files each contribute ~half the slots.
    """
    trace = retriever.retrieve_with_trace(question)
    chunks = trace.final_chunks

    # Group by source file
    by_source: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        by_source[c.get("source_file", "")].append(c)

    if len(by_source) >= 2:
        return chunks  # already diverse — nothing to do

    # Only one source came back — over-fetch and rebalance
    wide_trace = wide_retriever.retrieve_with_trace(question)
    all_chunks = wide_trace.final_chunks

    by_source_wide: dict[str, list[dict]] = defaultdict(list)
    for c in all_chunks:
        by_source_wide[c.get("source_file", "")].append(c)

    if len(by_source_wide) < 2:
        # Still only one source — return normal results unchanged
        return chunks

    # Rank sources by the score of their best chunk
    ranked_sources = sorted(
        by_source_wide.keys(),
        key=lambda s: by_source_wide[s][0]["score"],
        reverse=True,
    )

    half = top_k // 2
    primary   = by_source_wide[ranked_sources[0]][:half]
    secondary = by_source_wide[ranked_sources[1]][:half]
    remainder = top_k - len(primary) - len(secondary)
    rest = [c for s in ranked_sources[2:] for c in by_source_wide[s]][:remainder]
    return primary + secondary + rest


# ── LLM worker ────────────────────────────────────────────────────────────────

def _call_llm(args: tuple) -> tuple[int, dict]:
    """Thread worker: call the LLM for one pre-retrieved example."""
    idx, item, llm, system_prompt, config = args
    chunks = item.get("retrieved_chunks", [])
    t0 = time.time()

    if not chunks:
        item["rag_answer"]         = _FALLBACK
        item["rag_model"]          = llm.model
        item["generation_time_s"]  = 0.0
        return idx, item

    try:
        prompt   = build_prompt(item["question"], chunks, config.max_chunk_chars)
        raw      = llm.complete(system_prompt, prompt,
                                temperature=config.temperature,
                                max_tokens=config.max_tokens)
        cleaned, _ = parse_citations(raw, chunks)
        item["rag_answer"] = cleaned
    except Exception as e:
        print(f"  ERROR [{item['id']}] LLM: {e}", file=sys.stderr, flush=True)
        item["rag_answer"] = ""

    item["rag_model"]         = llm.model
    item["generation_time_s"] = round(time.time() - t0, 2)
    return idx, item


# ── Main generation logic ─────────────────────────────────────────────────────

def run(
    input_path: Path | None  = None,
    output_path: Path | None = None,
    model: str   = "gpt-5.4-mini",
    top_k: int   = 15,
    workers: int = 4,
    limit: int | None = None,
) -> Path:
    input_path  = input_path  or (DATA_DIR / "synthetic_test_set.jsonl")
    output_path = output_path or (DATA_DIR / "rag_outputs.jsonl")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n── Stage 2: RAG answer generation ───────────────────────────────")
    print(f"  Input   : {input_path}")
    print(f"  Model   : {model}  |  top_k={top_k}  |  workers={workers}")

    if not input_path.exists():
        sys.exit(f"Input not found: {input_path} — run build_test_set.py first")

    # Load test set
    items: list[dict] = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))

    if limit:
        items = items[:limit]
    n = len(items)
    print(f"  Loaded {n} questions\n")

    config = AnswerConfig(model=model, top_k=top_k)

    # ── Phase 1: sequential retrieval ────────────────────────────────────────
    print(f"  Retrieving chunks (sequential)...", flush=True)
    retriever      = HybridRetriever(RetrieverConfig(top_k=top_k))
    wide_retriever = HybridRetriever(RetrieverConfig(top_k=top_k * 3))
    t_ret = time.time()

    n_comparative = 0
    for i, item in enumerate(items, start=1):
        try:
            if _is_comparative(item):
                chunks = _diverse_retrieve(retriever, wide_retriever,
                                           item["question"], top_k)
                n_comparative += 1
            else:
                trace  = retriever.retrieve_with_trace(item["question"])
                chunks = trace.final_chunks
            item["retrieved_chunks"] = chunks
            item["n_chunks"]         = len(chunks)
        except Exception as e:
            print(f"  ERROR [{item['id']}] retrieval: {e}", file=sys.stderr)
            item["retrieved_chunks"] = []
            item["n_chunks"]         = 0

    print(f"  Retrieval done in {round(time.time() - t_ret, 1)}s  "
          f"(avg {sum(x['n_chunks'] for x in items)/n:.1f} chunks/question, "
          f"{n_comparative} comparative questions with diverse retrieval)")

    # ── Phase 2: parallel LLM calls ──────────────────────────────────────────
    print(f"\n  Calling LLM ({workers} workers)...", flush=True)
    llm           = LLMClient(config)
    system_prompt = load_system_prompt()
    completed     = 0
    results: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_call_llm, (i, item, llm, system_prompt, config)): i
            for i, item in enumerate(items)
        }
        for future in as_completed(futures):
            idx, updated = future.result()
            results[idx] = updated
            completed += 1
            item = updated
            print(
                f"  [{completed:3d}/{n}] {item['id']}: "
                f"{item['n_chunks']} chunks, {item.get('generation_time_s', 0)}s",
                flush=True,
            )

    items = [results[i] for i in range(n)]

    # ── Write output (strip retrieved_chunks — they're large) ────────────────
    with open(output_path, "w", encoding="utf-8") as f:
        for item in items:
            out = {k: v for k, v in item.items() if k != "retrieved_chunks"}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    print(f"\n  ✓ {n} outputs written → {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 2: generate RAG answers")
    parser.add_argument("--input",   type=Path, default=None,
                        help="Input JSONL (default: evals/data/synthetic_test_set.jsonl)")
    parser.add_argument("--output",  type=Path, default=None,
                        help="Output JSONL (default: evals/data/rag_outputs.jsonl)")
    parser.add_argument("--model",   default="gpt-5.4-mini")
    parser.add_argument("--top-k",   type=int, default=15)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit",   type=int, default=None,
                        help="Only process first N questions (spot-check)")
    args = parser.parse_args()

    run(
        input_path=args.input,
        output_path=args.output,
        model=args.model,
        top_k=args.top_k,
        workers=args.workers,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
