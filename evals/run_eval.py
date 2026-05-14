#!/usr/bin/env python3
"""
RAG Evaluation Orchestrator.

Runs all four evaluation tiers against the gold dataset and writes results
to evals/results/.

Usage:
    # Full evaluation (all tiers):
    python -m evals.run_eval

    # Skip expensive LLM judges (Tier 3 + 4):
    python -m evals.run_eval --no-llm-judge

    # Skip BERTScore (slower, needs transformers):
    python -m evals.run_eval --no-bertscore

    # Evaluate only a subset (useful during development):
    python -m evals.run_eval --limit 5

    # Use a specific model for generation:
    python -m evals.run_eval --model gpt-5.4-mini

    # Dry-run: only print what would be evaluated without calling any APIs:
    python -m evals.run_eval --dry-run

Results are written to:
    evals/results/<timestamp>.json     — full per-question breakdown
    evals/results/summary.md           — aggregated table

Env vars required (same as the main RAG system):
    OPENAI_API_KEY  — used for both generation and LLM-as-judge
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Resolve project root so imports work regardless of cwd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.answer.answer import AnswerEngine, AnswerConfig, LLMClient
from evals.metrics.rouge_eval       import run_tier1, aggregate_tier1
from evals.metrics.retrieval_eval   import run_tier2, aggregate_tier2
from evals.metrics.faithfulness_eval import run_tier3, aggregate_tier3
from evals.metrics.relevance_eval   import run_tier4, aggregate_tier4

GOLD_DATASET  = Path(__file__).parent / "gold_dataset.jsonl"
RESULTS_DIR   = Path(__file__).parent / "results"


# ── Scoring thresholds (from evaluation_plan.md) ──────────────────────────────

THRESHOLDS = {
    "rouge1_f":           {"acceptable": 0.35, "good": 0.50},
    "rouge2_f":           {"acceptable": 0.15, "good": 0.25},
    "rougeL_f":           {"acceptable": 0.30, "good": 0.45},
    "bertscore_f":        {"acceptable": 0.85, "good": 0.90},
    "precision":          {"acceptable": 0.40, "good": 0.60},
    "recall":             {"acceptable": 0.60, "good": 0.80},
    "mrr":                {"acceptable": 0.50, "good": 0.70},
    "faithfulness_score": {"acceptable": 0.90, "good": 0.95},
    "relevance_score":    {"acceptable": 4.0,  "good": 4.5},
}


def _status(value: float, metric: str) -> str:
    t = THRESHOLDS.get(metric)
    if t is None:
        return ""
    if value >= t["good"]:
        return "✓ GOOD"
    if value >= t["acceptable"]:
        return "~ OK"
    return "✗ BELOW"


# ── Gold dataset loading ───────────────────────────────────────────────────────

def load_gold(path: Path = GOLD_DATASET) -> list[dict]:
    if not path.exists():
        sys.exit(f"Gold dataset not found: {path}")
    examples = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"Invalid JSON on line {lineno} of {path}: {e}")
    return examples


# ── Generation step ────────────────────────────────────────────────────────────

def generate_answers(
    examples: list[dict],
    engine: AnswerEngine,
) -> list[dict]:
    """
    Call the RAG engine for each example, storing the generated answer and
    retrieved chunks back into the example dict.

    Modifies examples in-place. Returns them for chaining.
    """
    n = len(examples)
    for i, ex in enumerate(examples, start=1):
        print(f"  [{i}/{n}] {ex['id']}: {ex['question'][:70]}...", flush=True)
        t0 = time.time()
        try:
            result = engine.answer_with_trace(ex["question"])
            ex["generated_answer"] = result.answer_text
            ex["retrieved_chunks"] = result.retrieval_trace.final_chunks if result.retrieval_trace else []
            ex["model_used"]       = result.model_used
            ex["n_chunks_used"]    = result.n_chunks_used
        except Exception as e:
            print(f"    ERROR generating answer: {e}", file=sys.stderr)
            ex["generated_answer"] = ""
            ex["retrieved_chunks"] = []
            ex["model_used"]       = "error"
            ex["n_chunks_used"]    = 0
        ex["generation_time_s"] = round(time.time() - t0, 2)
        print(f"    → {ex['n_chunks_used']} chunks, {ex['generation_time_s']}s", flush=True)
    return examples


# ── Results writing ────────────────────────────────────────────────────────────

def write_full_results(
    examples:    list[dict],
    tier1:       list[dict],
    tier2:       list[dict],
    tier3:       list[dict],
    tier4:       list[dict],
    aggregates:  dict,
    timestamp:   str,
) -> Path:
    """Write the full per-question JSON to results/<timestamp>.json."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Merge all per-question result dicts by id
    merged: dict[str, dict] = {}
    for ex in examples:
        merged[ex["id"]] = {
            "id":               ex["id"],
            "question":         ex["question"],
            "reference_answer": ex.get("reference_answer", ""),
            "generated_answer": ex.get("generated_answer", ""),
            "source_files":     ex.get("source_files", []),
            "model_used":       ex.get("model_used", ""),
            "n_chunks_used":    ex.get("n_chunks_used", 0),
            "generation_time_s": ex.get("generation_time_s", 0),
        }

    for r in tier1:
        merged.setdefault(r["id"], {}).update({k: v for k, v in r.items() if k != "id"})
    for r in tier2:
        merged.setdefault(r["id"], {}).update({k: v for k, v in r.items() if k != "id"})
    for r in tier3:
        merged.setdefault(r["id"], {}).update({k: v for k, v in r.items() if k != "id"})
    for r in tier4:
        merged.setdefault(r["id"], {}).update({k: v for k, v in r.items() if k != "id"})

    output = {
        "timestamp":  timestamp,
        "n_examples": len(examples),
        "aggregates": aggregates,
        "per_question": list(merged.values()),
    }

    out_path = RESULTS_DIR / f"{timestamp}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def write_summary(aggregates: dict, timestamp: str) -> Path:
    """Write aggregated metric table to results/summary.md."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# RAG Evaluation Summary",
        f"",
        f"**Run:** {timestamp}  ",
        f"**Examples:** {aggregates.get('n_examples', '?')}",
        f"",
    ]

    sections = {
        "Tier 1 — Generation Quality": [
            ("ROUGE-1 F1",   "rouge1_f"),
            ("ROUGE-2 F1",   "rouge2_f"),
            ("ROUGE-L F1",   "rougeL_f"),
            ("BERTScore F1", "bertscore_f"),
            ("METEOR",       "meteor"),
        ],
        "Tier 2 — Retrieval Quality": [
            ("Context Precision@15", "precision"),
            ("Context Recall@15",    "recall"),
            ("MRR",                  "mrr"),
        ],
        "Tier 3 — Faithfulness": [
            ("Faithfulness Score",      "faithfulness_score"),
            ("Avg Unsupported Claims",  "avg_unsupported_claims"),
        ],
        "Tier 4 — Answer Relevance": [
            ("Relevance Score (1–5)", "relevance_score"),
        ],
    }

    for section_title, metrics in sections.items():
        lines.append(f"## {section_title}")
        lines.append("")
        lines.append("| Metric | Score | Status |")
        lines.append("|---|---|---|")
        for label, key in metrics:
            val = aggregates.get(key)
            if val is None:
                lines.append(f"| {label} | — | (not run) |")
            else:
                status = _status(float(val), key)
                lines.append(f"| {label} | {val} | {status} |")
        lines.append("")

    out_path = RESULTS_DIR / "summary.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run RAG evaluation against the gold dataset"
    )
    parser.add_argument(
        "--model", default="gpt-5.4-mini",
        help="LLM model to use for answer generation (default: gpt-5.4-mini)",
    )
    parser.add_argument(
        "--top-k", type=int, default=15,
        help="Number of chunks to retrieve per question (default: 15)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Evaluate only the first N examples (for quick development runs)",
    )
    parser.add_argument(
        "--no-llm-judge", action="store_true",
        help="Skip Tier 3 (faithfulness) and Tier 4 (relevance) LLM judges",
    )
    parser.add_argument(
        "--no-bertscore", action="store_true",
        help="Skip BERTScore computation (faster, no GPU required)",
    )
    parser.add_argument(
        "--no-meteor", action="store_true",
        help="Skip METEOR computation",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Load dataset and print questions without calling any APIs",
    )
    parser.add_argument(
        "--gold", type=Path, default=GOLD_DATASET,
        help=f"Path to gold dataset JSONL (default: {GOLD_DATASET})",
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n══ SEC EDGAR RAG Evaluation  [{timestamp}] ══\n")

    # Load gold dataset
    examples = load_gold(args.gold)
    if args.limit:
        examples = examples[: args.limit]
    print(f"Loaded {len(examples)} examples from {args.gold}\n")

    if args.dry_run:
        print("Dry run — questions that would be evaluated:")
        for i, ex in enumerate(examples, 1):
            print(f"  {i:2d}. [{ex['id']}] {ex['question'][:80]}")
        return

    # ── Step 1: Generate answers ─────────────────────────────────────────────
    print("Step 1/4 — Generating answers...\n")
    engine_config = AnswerConfig(model=args.model, top_k=args.top_k)
    engine        = AnswerEngine(engine_config)
    examples      = generate_answers(examples, engine)
    print()

    aggregates: dict = {"n_examples": len(examples)}

    # ── Step 2: Tier 2 — Retrieval (no API cost) ─────────────────────────────
    print("Step 2/4 — Tier 2: Retrieval metrics...")
    t2_results  = run_tier2(examples)
    t2_agg      = aggregate_tier2(t2_results)
    aggregates.update(t2_agg)
    print(f"  Precision@{args.top_k}: {t2_agg.get('precision')}  "
          f"Recall@{args.top_k}: {t2_agg.get('recall')}  "
          f"MRR: {t2_agg.get('mrr')}")
    print()

    # ── Step 3: Tier 1 — ROUGE + BERTScore + METEOR ──────────────────────────
    print("Step 3/4 — Tier 1: ROUGE / BERTScore / METEOR...")
    t1_results = run_tier1(
        examples,
        skip_bertscore=args.no_bertscore,
        skip_meteor=args.no_meteor,
    )
    t1_agg = aggregate_tier1(t1_results)
    aggregates.update(t1_agg)
    print(f"  ROUGE-1: {t1_agg.get('rouge1_f')}  "
          f"ROUGE-2: {t1_agg.get('rouge2_f')}  "
          f"ROUGE-L: {t1_agg.get('rougeL_f')}")
    if not args.no_bertscore:
        print(f"  BERTScore F1: {t1_agg.get('bertscore_f')}")
    if not args.no_meteor:
        print(f"  METEOR: {t1_agg.get('meteor')}")
    print()

    # ── Step 4: Tier 3 + 4 — LLM judges (cost ~$0.001/question) ─────────────
    t3_results: list[dict] = []
    t4_results: list[dict] = []

    if not args.no_llm_judge:
        print("Step 4/4 — Tier 3+4: Faithfulness + Relevance judges...")
        # Use a cheap judge model; same client as generation
        judge_config = AnswerConfig(model="gpt-5.4-mini")
        judge_client = LLMClient(judge_config)

        t3_results = run_tier3(examples, judge_client)
        t3_agg     = aggregate_tier3(t3_results)
        aggregates.update(t3_agg)
        print(f"  Faithfulness: {t3_agg.get('faithfulness_score')}")

        t4_results = run_tier4(examples, judge_client)
        t4_agg     = aggregate_tier4(t4_results)
        aggregates.update(t4_agg)
        print(f"  Relevance: {t4_agg.get('relevance_score')} / 5.0")
    else:
        print("Step 4/4 — LLM judges skipped (--no-llm-judge)")
    print()

    # ── Write results ─────────────────────────────────────────────────────────
    json_path = write_full_results(
        examples, t1_results, t2_results, t3_results, t4_results,
        aggregates, timestamp
    )
    summary_path = write_summary(aggregates, timestamp)

    print(f"Results written to:")
    print(f"  {json_path}")
    print(f"  {summary_path}")
    print()
    print("── Summary ──────────────────────────────────────────────────────────")

    # Print summary table to stdout
    summary_text = summary_path.read_text(encoding="utf-8")
    print(summary_text)


if __name__ == "__main__":
    main()
