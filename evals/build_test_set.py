#!/usr/bin/env python3
"""
Stage 1 — Sampler LLM.

Reads stratified batches of SEC filing excerpts from edgar_corpus/, calls a
Sampler LLM to generate (question, reference_answer, source_files,
question_type) triples, and writes evals/data/synthetic_test_set.jsonl.

Stratification dimensions:
  - Sector   (9 sectors, even representation)
  - Year     (2022–2026, spread within each sector allocation)
  - Filing type  (10-K vs 10-Q, 50/50 within each allocation)

Usage:
    python -m evals.build_test_set
    python -m evals.build_test_set --files-per-sector 8 --questions-per-batch 5
    python -m evals.build_test_set --sampler-model gpt-5.4
    python -m evals.build_test_set --workers 8
    python -m evals.build_test_set --dry-run   # print selected files, no API calls
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORPUS_DIR  = ROOT / "edgar_corpus"
DATA_DIR    = Path(__file__).parent / "data"

# ── Sector → ticker mapping ────────────────────────────────────────────────────
# Each ticker appears in exactly one sector (primary classification).
SECTOR_MAP: dict[str, list[str]] = {
    "Technology":          ["AAPL", "MSFT", "NVDA", "META", "GOOG", "AMZN",
                            "AMD", "INTC", "ADBE", "ORCL", "CRM", "CSCO", "IBM"],
    "Media_Entertainment": ["NFLX", "DIS", "CMCSA"],
    "Healthcare_Pharma":   ["PFE", "JNJ", "MRK", "LLY", "ABBV", "UNH", "TMO"],
    "Financial_Banking":   ["JPM", "GS", "MS", "BAC", "BLK", "AXP", "MA", "V", "BRK"],
    "Energy":              ["XOM", "CVX"],
    "Consumer_Retail":     ["WMT", "COST", "MCD", "SBUX", "KO", "PEP", "TGT",
                            "NKE", "PG", "HD"],
    "Industrial_Defense":  ["CAT", "DE", "BA", "RTX", "LMT", "GE"],
    "Telecom":             ["T", "VZ"],
    "Automotive":          ["TSLA"],
}

SAMPLER_SYSTEM = """\
You are creating evaluation questions for a financial research RAG system that
answers questions about SEC filings (10-K annual reports and 10-Q quarterly reports).

You will be given excerpts from one or more SEC filings. Your task is to generate
exactly {n} question–answer pairs that test whether the RAG system can retrieve
and synthesise the right information.

Rules:
1. Every question must be answerable solely from the provided excerpts — do not
   invent facts not present in the text.
2. Each reference answer must be 3–5 sentences, factually grounded, and include
   specific details (numbers, dates, named risks, product names, percentages) from
   the excerpts wherever possible.
3. Vary question types across the batch — include at least one risk-factor question
   and one financial or operational question. If multiple filings are provided,
   include at least one question that requires information from more than one of them.
4. question_type must be one of: risk | financial | regulatory | comparative | operational
5. source_files must list only the filenames provided below, using the exact names given.

Do NOT generate questions about:
- Exhibit listings (e.g., "what exhibits were filed?", "what documents were attached?")
- Disclosure controls and procedures certifications (e.g., "were disclosure controls effective?")
- Rule 10b5-1 trading arrangements adopted or terminated by officers or directors
- Iran, OFAC, or sanctions-related disclosures
- Internal control over financial reporting certifications
- Forward-looking statement boilerplate disclaimers
- Signatures or certifying officers

Focus exclusively on questions that test understanding of business fundamentals,
financial performance, risk exposure, competitive dynamics, and strategic direction.

Return ONLY a valid JSON array — no markdown, no explanation, no code fences:
[
  {{
    "question": "...",
    "reference_answer": "...",
    "source_files": ["TICKER_TYPE_DATE_full.txt"],
    "question_type": "risk"
  }},
  ...
]"""

SAMPLER_USER = """\
Filing excerpts:

{excerpts}"""


# ── Corpus file parsing ────────────────────────────────────────────────────────

def parse_corpus_files(corpus_dir: Path) -> list[dict]:
    """
    Parse metadata from every *_full.txt file in corpus_dir.
    Returns list of dicts: {filename, ticker, filing_type, year, date, path}.
    """
    files = []
    for p in sorted(corpus_dir.glob("*_full.txt")):
        name  = p.name
        parts = name.replace("_full.txt", "").split("_")
        if len(parts) < 3:
            continue

        ticker = parts[0]
        ftype  = parts[1]  # "10K" or "10Q"
        if ftype not in ("10K", "10Q"):
            continue

        # Date is always the last segment before _full.txt
        # e.g. AAPL_10K_2022Q3_2022-10-28_full.txt → date = "2022-10-28"
        date_str = parts[-1]
        if not re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            continue

        year = int(date_str[:4])

        files.append({
            "filename":    name,
            "ticker":      ticker,
            "filing_type": ftype,
            "year":        year,
            "date":        date_str,
            "path":        p,
        })
    return files


def _ticker_to_sector(sector_map: dict[str, list[str]]) -> dict[str, str]:
    return {ticker: sector for sector, tickers in sector_map.items()
            for ticker in tickers}


# ── Stratified sampling ────────────────────────────────────────────────────────

def stratified_sample(
    files: list[dict],
    files_per_sector: int,
    seed: int = 42,
) -> dict[str, list[dict]]:
    """
    Select `files_per_sector` files per sector, spread across years and filing
    types. Returns {sector: [file_meta, ...]}.

    Within each sector allocation:
      - Half 10-K, half 10-Q (or best available)
      - Spread across different years (no two files from the same year unless
        the sector has fewer years than slots)
      - Different tickers where possible
    """
    rng = random.Random(seed)
    t2s = _ticker_to_sector(SECTOR_MAP)

    by_sector: dict[str, list[dict]] = defaultdict(list)
    for f in files:
        sector = t2s.get(f["ticker"])
        if sector:
            by_sector[sector].append(f)

    selected: dict[str, list[dict]] = {}

    for sector, candidates in by_sector.items():
        n_10k = files_per_sector // 2
        n_10q = files_per_sector - n_10k

        pool_10k = [f for f in candidates if f["filing_type"] == "10K"]
        pool_10q = [f for f in candidates if f["filing_type"] == "10Q"]

        def _pick_spread(pool: list[dict], n: int) -> list[dict]:
            """Pick n files spread across years and tickers."""
            if not pool:
                return []
            rng.shuffle(pool)
            # Sort by year so we can do round-robin across years
            by_year: dict[int, list[dict]] = defaultdict(list)
            for f in pool:
                by_year[f["year"]].append(f)
            years = sorted(by_year.keys())
            result, seen_tickers = [], set()
            # First pass: one per year, prefer unseen tickers
            for year in years:
                if len(result) >= n:
                    break
                choices = sorted(by_year[year], key=lambda f: f["ticker"] in seen_tickers)
                result.append(choices[0])
                seen_tickers.add(choices[0]["ticker"])
            # Second pass: fill remaining slots from any year
            remaining = [f for f in pool if f not in result]
            rng.shuffle(remaining)
            for f in remaining:
                if len(result) >= n:
                    break
                result.append(f)
            return result[:n]

        picked_10k = _pick_spread(pool_10k, n_10k)
        picked_10q = _pick_spread(pool_10q, n_10q)

        # If one type is scarce, fill from the other
        deficit = files_per_sector - len(picked_10k) - len(picked_10q)
        if deficit > 0:
            used = set(id(f) for f in picked_10k + picked_10q)
            extras = [f for f in candidates if id(f) not in used]
            picked_10k += _pick_spread(extras, deficit)

        selected[sector] = picked_10k + picked_10q

    return selected


# ── File reading ───────────────────────────────────────────────────────────────

# Sections to look for, in priority order.
# Each entry is (regex_pattern, min_pos) where min_pos prevents matching a
# TOC entry that appears near the top of the file.
_SECTION_PATTERNS: list[tuple[str, int]] = [
    (r"item\s+1a[\.\s\xa0]+risk factors",    5_000),   # Risk Factors (10-K)
    (r"item\s+1a[\.\s\xa0]+risk factor",     5_000),
    (r"item\s+7[\.\s\xa0]+management",       5_000),   # MD&A (10-K)
    (r"item\s+2[\.\s\xa0]+management",       3_000),   # MD&A (10-Q)
    (r"item\s+1[\.\s\xa0]+business",         5_000),   # Business (10-K)
    (r"forward-looking statements",          3_000),
    (r"this annual report on form 10-k",     3_000),
    (r"this quarterly report on form 10-q",  3_000),
]


_INLINE_REF_SIGNALS = (
    "see ", "see\xa0", "in part", "part i,", "part ii,",
    "of this form", "under the heading", "discussed in",
    ", item", "including item",
)


def _find_narrative_start(text: str) -> int:
    """
    Return the character offset where substantive narrative content begins,
    skipping the XBRL metadata preamble at the top of each SEC filing.

    Strategy: find the first occurrence of a known section header that is:
      - past a minimum offset (avoids matching early TOC entries)
      - not a table-of-contents entry (no '| digits' immediately after it)
      - not an inline cross-reference ('see Item 1A', 'Part I, Item 1A', etc.)
    """
    for pattern, min_pos in _SECTION_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if m.start() < min_pos:
                continue
            # Skip TOC entries: "Item X. | Section | page_num"
            post = text[m.start(): m.start() + 80]
            if re.search(r"\|\s*\d+", post):
                continue
            # Skip inline cross-references: text before contains reference markers
            pre = text[max(0, m.start() - 60): m.start()].lower()
            if any(sig in pre for sig in _INLINE_REF_SIGNALS):
                continue
            return m.start()
    return 0  # fallback: start of file


def read_excerpt(path: Path, max_chars: int = 12_000) -> str:
    """
    Read up to max_chars characters of narrative content from a filing,
    starting from the first substantive section (Item 1A, Item 7, etc.)
    and skipping the XBRL metadata preamble.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        start = _find_narrative_start(text)
        return text[start: start + max_chars]
    except Exception as e:
        print(f"  Warning: could not read {path.name}: {e}", file=sys.stderr)
        return ""


def build_excerpts_block(
    batch: list[dict],
    max_chars_per_file: int,
) -> str:
    """Format a batch of files into a single prompt block."""
    blocks = []
    for f in batch:
        excerpt = read_excerpt(f["path"], max_chars_per_file)
        header  = (
            f"=== {f['filename']} "
            f"({f['filing_type']} filed {f['date']}, ticker {f['ticker']}) ==="
        )
        blocks.append(f"{header}\n{excerpt}")
    return "\n\n".join(blocks)


# ── LLM call ──────────────────────────────────────────────────────────────────

def call_sampler(
    batch: list[dict],
    llm_client,
    questions_per_batch: int,
    max_chars_per_file: int,
    max_retries: int = 2,
) -> list[dict]:
    """
    Call the Sampler LLM with a batch of files.
    Returns a list of QA dicts (possibly empty on parse failure).
    """
    excerpts = build_excerpts_block(batch, max_chars_per_file)
    system   = SAMPLER_SYSTEM.format(n=questions_per_batch)
    user     = SAMPLER_USER.format(excerpts=excerpts)

    for attempt in range(max_retries + 1):
        try:
            raw = llm_client.complete(
                system=system,
                user=user,
                temperature=0.7,
                max_tokens=2048,
            )
            # Strip markdown fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            qa_list = json.loads(raw)
            if not isinstance(qa_list, list):
                raise ValueError("Expected JSON array")
            # Validate and normalise
            valid = []
            for item in qa_list:
                if "question" not in item or "reference_answer" not in item:
                    continue
                item.setdefault("source_files",  [f["filename"] for f in batch])
                item.setdefault("question_type", "risk")
                valid.append(item)
            return valid
        except (json.JSONDecodeError, ValueError) as e:
            if attempt < max_retries:
                time.sleep(2)
                continue
            print(f"  Warning: sampler parse error on batch "
                  f"{[f['filename'] for f in batch]}: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"  Warning: sampler call failed: {e}", file=sys.stderr)
            return []


# ── Batch builder ─────────────────────────────────────────────────────────────

def build_batches(
    selected: dict[str, list[dict]],
    batch_size: int = 2,
    seed: int = 42,
) -> list[dict]:
    """
    Turn selected files into batches.

    Strategy:
      - Pairs of files from the same sector but different years → temporal comparisons
      - Single files when the sector has an odd count
      - Occasionally pair files from same ticker different years when available
    """
    rng = random.Random(seed)
    batches = []

    for sector, files in selected.items():
        rng.shuffle(files)
        i = 0
        while i < len(files):
            chunk = files[i: i + batch_size]
            batches.append({"sector": sector, "files": chunk})
            i += batch_size

    return batches


# ── Main ──────────────────────────────────────────────────────────────────────

def _sample_batch_worker(args: tuple) -> tuple[int, str, list[dict]]:
    """Thread worker: read excerpts and call the Sampler LLM for one batch."""
    idx, batch, client, questions_per_batch = args
    files  = batch["files"]
    sector = batch["sector"]
    max_chars = 12_000 if len(files) == 1 else 5_000
    qa_list   = call_sampler(files, client, questions_per_batch, max_chars)
    return idx, sector, qa_list


def run(
    sampler_model: str = "gpt-5.4",
    files_per_sector: int = 8,
    questions_per_batch: int = 5,
    batch_size: int = 2,
    seed: int = 42,
    dry_run: bool = False,
    workers: int = 5,
    output_path: Path | None = None,
) -> Path:
    from src.answer.answer import LLMClient, AnswerConfig

    output_path = output_path or (DATA_DIR / "synthetic_test_set.jsonl")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n── Stage 1: Building synthetic test set ──────────────────────────")
    print(f"  Corpus  : {CORPUS_DIR}")
    print(f"  Model   : {sampler_model}")
    print(f"  Files/sector: {files_per_sector}  |  Questions/batch: {questions_per_batch}")

    # Parse all corpus files
    all_files = parse_corpus_files(CORPUS_DIR)
    print(f"  Found {len(all_files)} corpus files across "
          f"{len(set(f['ticker'] for f in all_files))} tickers\n")

    # Stratified selection
    selected = stratified_sample(all_files, files_per_sector, seed)
    total_selected = sum(len(v) for v in selected.values())
    print(f"  Stratified selection: {total_selected} files")
    for sector, files in selected.items():
        years  = sorted(set(f["year"]        for f in files))
        types  = sorted(set(f["filing_type"] for f in files))
        print(f"    {sector:<22} {len(files):2d} files  "
              f"years={years}  types={types}")

    # Build batches
    batches = build_batches(selected, batch_size, seed)
    print(f"\n  {len(batches)} batches → "
          f"~{len(batches) * questions_per_batch} questions expected\n")

    # Save corpus sample audit trail
    audit = {
        "seed": seed, "files_per_sector": files_per_sector,
        "sampler_model": sampler_model,
        "selected": {
            sector: [f["filename"] for f in files]
            for sector, files in selected.items()
        },
    }
    audit_path = DATA_DIR / "corpus_sample.json"
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(f"  Corpus sample saved → {audit_path}")

    if dry_run:
        print("\n  Dry run — skipping LLM calls.")
        return output_path

    # Init LLM client
    cfg    = AnswerConfig(model=sampler_model)
    client = LLMClient(cfg)

    # Generate Q&A pairs in parallel — each batch's API call is independent
    print(f"  Calling Sampler LLM ({workers} workers)...\n", flush=True)
    batch_results: dict[int, tuple[str, list[dict]]] = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_sample_batch_worker, (i, batch, client, questions_per_batch)): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            idx, sector, qa_list = future.result()
            batch_results[idx] = (sector, qa_list)
            completed += 1
            batch   = batches[idx]
            names   = [f["filename"] for f in batch["files"]]
            print(
                f"  [{completed:3d}/{len(batches)}] {sector:<22} "
                f"→ {len(qa_list)} questions  {names}",
                flush=True,
            )

    # Assign IDs in original batch order for deterministic output
    all_qa: list[dict] = []
    seq = 0
    for i in range(len(batches)):
        sector, qa_list = batch_results[i]
        files = batches[i]["files"]
        for qa in qa_list:
            seq += 1
            ticker = files[0]["ticker"]
            year   = files[0]["year"]
            qa["id"]     = f"synth_{sector.lower()[:8]}_{ticker}_{year}_{seq:04d}"
            qa["sector"] = sector
            all_qa.append(qa)

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        for qa in all_qa:
            f.write(json.dumps(qa, ensure_ascii=False) + "\n")

    print(f"\n  ✓ {len(all_qa)} Q&A pairs written → {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 1: generate synthetic test set")
    parser.add_argument("--sampler-model",     default="gpt-5.4",
                        help="LLM model for sampling (default: gpt-5.4)")
    parser.add_argument("--files-per-sector",  type=int, default=8,
                        help="Files to select per sector (default: 8)")
    parser.add_argument("--questions-per-batch", type=int, default=5,
                        help="Questions to generate per batch (default: 5)")
    parser.add_argument("--batch-size",        type=int, default=2,
                        help="Files per batch sent to sampler (default: 2)")
    parser.add_argument("--workers",           type=int, default=5,
                        help="Parallel sampler API calls (default: 5)")
    parser.add_argument("--seed",              type=int, default=42)
    parser.add_argument("--dry-run",           action="store_true",
                        help="Print selected files without calling the LLM")
    parser.add_argument("--output",            type=Path, default=None,
                        help="Output path (default: evals/data/synthetic_test_set.jsonl)")
    args = parser.parse_args()

    run(
        sampler_model=args.sampler_model,
        files_per_sector=args.files_per_sector,
        questions_per_batch=args.questions_per_batch,
        batch_size=args.batch_size,
        seed=args.seed,
        dry_run=args.dry_run,
        workers=args.workers,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
