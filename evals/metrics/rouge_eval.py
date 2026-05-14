"""
Tier 1 — ROUGE-1/2/L, BERTScore, METEOR.

Usage:
    from evals.metrics.rouge_eval import compute_rouge, compute_bertscore, compute_meteor
    scores = compute_rouge("generated answer text", "reference answer text")
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def compute_rouge(hypothesis: str, reference: str) -> dict[str, float]:
    """Return ROUGE-1, ROUGE-2, ROUGE-L F1 scores."""
    try:
        from rouge_score import rouge_scorer
    except ImportError:
        sys.exit("rouge-score not installed — run: pip install rouge-score")

    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    scores = scorer.score(reference, hypothesis)
    return {
        "rouge1_f": round(scores["rouge1"].fmeasure, 4),
        "rouge1_p": round(scores["rouge1"].precision, 4),
        "rouge1_r": round(scores["rouge1"].recall, 4),
        "rouge2_f": round(scores["rouge2"].fmeasure, 4),
        "rouge2_p": round(scores["rouge2"].precision, 4),
        "rouge2_r": round(scores["rouge2"].recall, 4),
        "rougeL_f": round(scores["rougeL"].fmeasure, 4),
        "rougeL_p": round(scores["rougeL"].precision, 4),
        "rougeL_r": round(scores["rougeL"].recall, 4),
    }


def compute_bertscore(hypotheses: list[str], references: list[str]) -> list[dict[str, float]]:
    """
    Compute BERTScore for a batch of (hypothesis, reference) pairs.
    Batching is more efficient than calling one at a time.

    Returns a list of dicts with keys: bertscore_p, bertscore_r, bertscore_f.
    """
    try:
        from bert_score import score as bert_score_fn
    except ImportError:
        sys.exit("bert-score not installed — run: pip install bert-score")

    P, R, F1 = bert_score_fn(
        hypotheses,
        references,
        lang="en",
        verbose=False,
        device=None,  # auto-detect GPU/CPU
    )
    results = []
    for p, r, f in zip(P.tolist(), R.tolist(), F1.tolist()):
        results.append({
            "bertscore_p": round(p, 4),
            "bertscore_r": round(r, 4),
            "bertscore_f": round(f, 4),
        })
    return results


def compute_meteor(hypothesis: str, reference: str) -> dict[str, float]:
    """Return METEOR score (requires nltk and WordNet)."""
    try:
        import nltk
        from nltk.translate.meteor_score import meteor_score as nltk_meteor
    except ImportError:
        sys.exit("nltk not installed — run: pip install nltk")

    # Download required data silently on first run
    for resource in ("wordnet", "punkt", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{resource}")
        except LookupError:
            try:
                nltk.data.find(f"corpora/{resource}")
            except LookupError:
                nltk.download(resource, quiet=True)

    ref_tokens  = nltk.word_tokenize(reference.lower())
    hyp_tokens  = nltk.word_tokenize(hypothesis.lower())
    score       = nltk_meteor([ref_tokens], hyp_tokens)
    return {"meteor": round(float(score), 4)}


def run_tier1(
    examples: list[dict],
    skip_bertscore: bool = False,
    skip_meteor: bool = False,
) -> list[dict]:
    """
    Evaluate all examples with Tier 1 metrics.

    Each example dict must have:
        generated_answer: str
        reference_answer: str
        id: str

    Returns a list of result dicts (one per example) with all metric keys.
    """
    results = []
    hypotheses = [e["generated_answer"] for e in examples]
    references  = [e["reference_answer"]  for e in examples]

    # BERTScore is batched for efficiency
    bert_scores: list[dict] = []
    if not skip_bertscore:
        print("  Computing BERTScore (batched)...", flush=True)
        bert_scores = compute_bertscore(hypotheses, references)

    for i, ex in enumerate(examples):
        r: dict = {"id": ex["id"]}
        r.update(compute_rouge(ex["generated_answer"], ex["reference_answer"]))
        if not skip_bertscore:
            r.update(bert_scores[i])
        if not skip_meteor:
            r.update(compute_meteor(ex["generated_answer"], ex["reference_answer"]))
        results.append(r)

    return results


def aggregate_tier1(results: list[dict]) -> dict[str, float]:
    """Average each metric across all results."""
    if not results:
        return {}
    keys = [k for k in results[0] if k != "id"]
    return {
        k: round(sum(r[k] for r in results if k in r) / len(results), 4)
        for k in keys
    }
