"""
Tier 2 — Retrieval quality: Context Precision, Context Recall, MRR.

Each gold example has source_files[] listing the files that contain the
answer. Retrieved chunks have a source_file metadata field. A chunk is
considered relevant if its source_file matches any of the gold source_files.

Usage:
    from evals.metrics.retrieval_eval import evaluate_retrieval
    result = evaluate_retrieval(retrieved_chunks, gold_source_files)
"""

from __future__ import annotations


def _is_relevant(chunk: dict, gold_files: list[str]) -> bool:
    """A chunk is relevant if its source_file is in the gold file list."""
    source = chunk.get("source_file", "")
    # Strip path components — gold dataset uses bare filenames
    source_base = source.split("/")[-1]
    return any(source_base == gf.split("/")[-1] for gf in gold_files)


def evaluate_retrieval(
    retrieved: list[dict],
    gold_files: list[str],
) -> dict[str, float]:
    """
    Compute precision, recall, and MRR for a single question.

    retrieved  — ordered list of chunk dicts (highest rank first), each with a
                 'source_file' key matching the format in gold_dataset.jsonl.
    gold_files — list of filenames that contain the answer (from the gold dataset).

    Returns dict with keys: precision, recall, mrr, n_retrieved, n_relevant_retrieved.
    """
    if not gold_files:
        # Adversarial question — expect empty retrieval or penalise retrieval
        n_retrieved = len(retrieved)
        precision   = 1.0 if n_retrieved == 0 else 0.0
        recall      = 1.0  # nothing to recall
        mrr         = 1.0 if n_retrieved == 0 else 0.0
        return {
            "precision": precision,
            "recall":    recall,
            "mrr":       mrr,
            "n_retrieved":          n_retrieved,
            "n_relevant_retrieved": 0,
        }

    relevant_retrieved = [c for c in retrieved if _is_relevant(c, gold_files)]
    n_retrieved        = len(retrieved)
    n_relevant         = len(relevant_retrieved)

    # Context Precision@k
    precision = n_relevant / n_retrieved if n_retrieved > 0 else 0.0

    # Context Recall@k (|relevant| is the number of gold files as a proxy)
    # We treat each gold file as one "relevant unit" — retrieved if any chunk
    # from that file was returned.
    covered_files = set()
    for c in retrieved:
        src = c.get("source_file", "").split("/")[-1]
        for gf in gold_files:
            if src == gf.split("/")[-1]:
                covered_files.add(gf)
    recall = len(covered_files) / len(gold_files) if gold_files else 1.0

    # MRR — rank of first relevant chunk (1-indexed)
    mrr = 0.0
    for rank, chunk in enumerate(retrieved, start=1):
        if _is_relevant(chunk, gold_files):
            mrr = 1.0 / rank
            break

    return {
        "precision":             round(precision, 4),
        "recall":                round(recall, 4),
        "mrr":                   round(mrr, 4),
        "n_retrieved":           n_retrieved,
        "n_relevant_retrieved":  n_relevant,
    }


def run_tier2(examples: list[dict]) -> list[dict]:
    """
    Evaluate all examples with Tier 2 metrics.

    Each example dict must have:
        id: str
        retrieved_chunks: list[dict]  — populated by run_eval.py
        source_files: list[str]       — from gold dataset
    """
    results = []
    for ex in examples:
        r = {"id": ex["id"]}
        r.update(evaluate_retrieval(ex["retrieved_chunks"], ex["source_files"]))
        results.append(r)
    return results


def aggregate_tier2(results: list[dict]) -> dict[str, float]:
    """Average precision, recall, mrr across all results."""
    if not results:
        return {}
    return {
        "precision": round(sum(r["precision"] for r in results) / len(results), 4),
        "recall":    round(sum(r["recall"]    for r in results) / len(results), 4),
        "mrr":       round(sum(r["mrr"]       for r in results) / len(results), 4),
    }
