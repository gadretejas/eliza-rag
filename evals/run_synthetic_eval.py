#!/usr/bin/env python3
"""
Orchestrator — runs all three evaluation stages end-to-end.

  Stage 1  build_test_set.py  — Sampler LLM generates Q&A pairs from corpus
  Stage 2  run_rag.py         — RAG system answers each question
  Stage 3  run_judge.py       — Judge LLM scores RAG answers vs reference

Usage:
    # Full run (all three stages):
    python -m evals.run_synthetic_eval

    # Skip Stage 1 if test set already exists:
    python -m evals.run_synthetic_eval --skip-build

    # Skip Stages 1 & 2 (re-judge existing RAG outputs):
    python -m evals.run_synthetic_eval --skip-build --skip-rag

    # Quick smoke-test (5 files/sector, 2 questions/batch, 10 RAG questions):
    python -m evals.run_synthetic_eval --files-per-sector 2 --questions-per-batch 2 --rag-limit 10

    # Dry run (shows selected corpus files, no API calls):
    python -m evals.run_synthetic_eval --dry-run

Model recommendations:
    --sampler-model gpt-5.4       (capable, creates ground truth)
    --rag-model     gpt-5.4-mini  (production model being evaluated)
    --judge-model   gpt-5.4-mini  (cheap, many parallel calls)

    For unbiased evaluation use different model families for sampler and judge.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.build_test_set import run as run_build
from evals.run_rag        import run as run_rag
from evals.run_judge      import run as run_judge

DATA_DIR = Path(__file__).parent / "data"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end synthetic RAG evaluation (3 stages)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Stage control
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip Stage 1 — use existing synthetic_test_set.jsonl")
    parser.add_argument("--skip-rag",   action="store_true",
                        help="Skip Stage 2 — use existing rag_outputs.jsonl")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Stage 1 dry run only — print selected corpus files")

    # Stage 1 options
    parser.add_argument("--sampler-model",       default="gpt-5.4",
                        help="Sampler LLM (default: gpt-5.4)")
    parser.add_argument("--files-per-sector",    type=int, default=8,
                        help="Files selected per sector (default: 8 → ~72 files)")
    parser.add_argument("--questions-per-batch", type=int, default=5,
                        help="Questions generated per file batch (default: 5)")
    parser.add_argument("--batch-size",          type=int, default=2,
                        help="Files per sampler batch (default: 2)")
    parser.add_argument("--sampler-workers",     type=int, default=5,
                        help="Parallel sampler API calls (default: 5)")
    parser.add_argument("--seed",                type=int, default=42)

    # Stage 2 options
    parser.add_argument("--rag-model",   default="gpt-5.4-mini",
                        help="RAG generation model (default: gpt-5.4-mini)")
    parser.add_argument("--top-k",       type=int, default=15)
    parser.add_argument("--rag-workers", type=int, default=4,
                        help="Parallel LLM workers for RAG generation (default: 4)")
    parser.add_argument("--rag-limit",   type=int, default=None,
                        help="Only generate answers for first N questions (spot-check)")

    # Stage 3 options
    parser.add_argument("--judge-model",    default="gpt-5.4-mini",
                        help="Judge LLM (default: gpt-5.4-mini)")
    parser.add_argument("--judge-workers",  type=int, default=6,
                        help="Parallel judge workers (default: 6)")
    parser.add_argument("--judge-limit",    type=int, default=None)

    args = parser.parse_args()

    if args.skip_rag and not args.skip_build:
        print("  Note: --skip-rag implies --skip-build", flush=True)
        args.skip_build = True

    t_total = time.time()
    print("\n══ Synthetic RAG Evaluation ═══════════════════════════════════════\n")

    test_set_path  = DATA_DIR / "synthetic_test_set.jsonl"
    rag_out_path   = DATA_DIR / "rag_outputs.jsonl"
    judge_out_path = DATA_DIR / "judge_results.jsonl"

    # ── Stage 1 ───────────────────────────────────────────────────────────────
    if not args.skip_build:
        t0 = time.time()
        run_build(
            sampler_model=args.sampler_model,
            files_per_sector=args.files_per_sector,
            questions_per_batch=args.questions_per_batch,
            batch_size=args.batch_size,
            seed=args.seed,
            dry_run=args.dry_run,
            workers=args.sampler_workers,
            output_path=test_set_path,
        )
        print(f"  Stage 1 done in {round(time.time()-t0, 1)}s\n")
        if args.dry_run:
            return
    else:
        print("  Stage 1 skipped — using existing test set\n")

    # ── Stage 2 ───────────────────────────────────────────────────────────────
    if not args.skip_rag:
        t0 = time.time()
        run_rag(
            input_path=test_set_path,
            output_path=rag_out_path,
            model=args.rag_model,
            top_k=args.top_k,
            workers=args.rag_workers,
            limit=args.rag_limit,
        )
        print(f"  Stage 2 done in {round(time.time()-t0, 1)}s\n")
    else:
        print("  Stage 2 skipped — using existing RAG outputs\n")

    # ── Stage 3 ───────────────────────────────────────────────────────────────
    t0 = time.time()
    run_judge(
        input_path=rag_out_path,
        output_path=judge_out_path,
        judge_model=args.judge_model,
        workers=args.judge_workers,
        limit=args.judge_limit,
    )
    print(f"  Stage 3 done in {round(time.time()-t0, 1)}s")
    print(f"\n══ Total: {round(time.time()-t_total, 1)}s ═══════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
