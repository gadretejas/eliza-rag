## Status: Implemented

The three-stage pipeline is fully implemented. Scripts are at `evals/build_test_set.py` (Stage 1), `evals/run_rag.py` (Stage 2), `evals/run_judge.py` (Stage 3), and `evals/run_synthetic_eval.py` (orchestrator). Data files land in `evals/data/` and results in `evals/results/`. Two eval runs have been completed (20260515_101548 and 20260517_092638). The file layout in the "File Layout" section below describes the planned layout; the actual layout differs — see the correction note at that section.

---

# Synthetic Evaluation Plan — LLM-as-Sampler + LLM-as-Judge

## Overview

The standard ROUGE/BERTScore approach breaks down for abstractive financial QA because
both the reference answer and the RAG-generated answer are independent paraphrases of
the same source material. They will naturally use different phrasing for the same correct
content, producing low lexical overlap scores even when the system is working perfectly
(confirmed: Relevance scored 4.6/5 while ROUGE-1 was 0.19 in the same run).

This plan replaces hand-written gold answers with **LLM-generated ground truth** and
replaces metric computation with **LLM-as-judge semantic comparison**. The result is a
faster, cheaper, more scalable, and more honest evaluation.

---

## The Three-LLM Pipeline

```
┌────────────────────────────────────────────────────────────────────┐
│  STAGE 1 — Sampler LLM                                             │
│  Reads raw filing batches from the corpus                          │
│  Generates (question, reference_answer, source_files) triples      │
└──────────────────────────┬─────────────────────────────────────────┘
                           │  synthetic_test_set.jsonl
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│  STAGE 2 — RAG System                                              │
│  Receives each question from the test set                          │
│  Generates an answer via retrieval + LLM                           │
│  Stores (question, rag_answer, retrieved_chunks)                   │
└──────────────────────────┬─────────────────────────────────────────┘
                           │  rag_outputs.jsonl
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│  STAGE 3 — Judge LLM                                               │
│  Receives question + reference_answer + rag_answer                 │
│  Scores RAG answer on correctness and completeness (1–5)           │
│  Returns score + reasoning                                         │
└────────────────────────────────────────────────────────────────────┘
```

**Key principle:** the Sampler and Judge must be different model families to prevent
style-matching bias (e.g. GPT-4o as Sampler, Claude as Judge). If the same model
samples and judges, it will reward answers that sound like itself regardless of
factual correctness.

---

## Stage 1 — Corpus Sampling Strategy

### Sampling dimensions

Rather than sampling one file per company (which biases toward tickers with more
filings), the test set is stratified along three orthogonal dimensions:

| Dimension | Rationale |
|---|---|
| **Sector** | Ensures the eval covers diverse financial language (pharma regulatory language ≠ semiconductor language ≠ banking language) |
| **Filing year** | Tests whether the RAG handles content from different time periods correctly |
| **Filing type** | 10-K (annual, comprehensive) vs 10-Q (quarterly, incremental) require different reasoning |

### Corpus breakdown

```
Total filings: 246 across 54 companies and 9 sectors

By year:         2022: 37   2023: 50   2024: 52   2025: 79   2026: 27
By filing type:  10-K: 89 (36%)   10-Q: 157 (64%)

Sectors (9):
  Technology         — AAPL MSFT NVDA META GOOG AMZN AMD INTC ADBE ORCL CRM CSCO IBM NFLX
  Healthcare/Pharma  — PFE JNJ MRK LLY ABBV UNH TMO
  Financial/Banking  — JPM GS MS BAC BLK AXP MA V BRK
  Energy             — XOM CVX
  Consumer/Retail    — WMT COST MCD SBUX KO PEP TGT NKE PG HD
  Media/Entertainment— DIS NFLX CMCSA
  Industrial/Defense — CAT DE BA RTX LMT GE
  Telecom            — T VZ CMCSA
  Automotive         — TSLA
```

### Stratified file selection (~72 files target)

Select 8 files per sector (9 sectors = 72 files). Within each sector allocation:

- **2 files from 10-K filings**
- **2 files from 10-Q filings**
- Spread across at least 3 different years (not all from the same year)
- Different companies within the sector where possible

This gives:
- 72 files × 5 questions each = **360 Q&A pairs**
- Even year coverage: each year 2022–2026 appears in multiple sectors
- Even type coverage: 50% 10-K / 50% 10-Q (oversampling 10-K vs corpus ratio
  since annual reports have more substantive content per file)

### Why not one-file-per-company?

With 54 companies and 246 files, one-per-company picks the most recently filed
document for each ticker. This biases the test set toward 2025–2026 filings and
underrepresents how the RAG handles historical queries. The sector × year × type
stratification ensures the eval is robust across all three dimensions.

---

## Stage 1 — Sampler Prompt Design

The sampler receives a batch of 1–5 raw filing excerpts and must generate questions
that are:
- Answerable **only** from the provided text (no external knowledge required)
- Specific enough that a wrong answer would be clearly distinguishable from the
  right one
- Varied in type (risk, financial metrics, regulatory, comparative)

```
System:
You are creating evaluation questions for a financial research RAG system.
You will be given excerpts from one or more SEC filings (10-K or 10-Q).

Your task is to generate exactly 5 question–answer pairs where:
1. Each question is answerable solely from the provided excerpts.
2. The reference answer is 3–5 sentences, factually grounded, and contains
   specific details (numbers, dates, named risks, policy names) from the text.
3. Questions vary in type: include at least one risk-factor question, one
   financial-metric question, and one that requires synthesising across
   multiple sections or filings if more than one is provided.
4. Do NOT invent facts not present in the excerpts.
5. Return ONLY valid JSON:
   [
     {
       "question": "...",
       "reference_answer": "...",
       "source_files": ["TICKER_TYPE_DATE_full.txt", ...],
       "question_type": "risk | financial | regulatory | comparative | operational"
     },
     ...
   ]

Excerpts:
{filing_excerpts}
```

### Batch sizes

| Batch type | Files | Expected question types |
|---|---|---|
| Single 10-K | 1 | Risk, financial metrics, business overview |
| Single 10-Q | 1 | Quarterly results, period-specific risks |
| Same company, different years | 2–3 | Year-over-year comparisons, trend questions |
| Same sector, different companies | 2–3 | Cross-company comparisons |
| Mixed (different sectors) | 4–5 | Sector-level aggregation questions |

---

## Stage 2 — RAG Answer Generation

Each question from the test set is passed to the RAG system unchanged. The
following are stored per question:

```jsonl
{
  "id": "synth_tech_nvda_2024_001",
  "question": "...",
  "reference_answer": "...",
  "source_files": ["NVDA_10K_2025-01-26_full.txt"],
  "question_type": "risk",
  "rag_answer": "...",
  "rag_chunks": [...],
  "rag_model": "gpt-5.4-mini",
  "generation_time_s": 3.2
}
```

No modification to the RAG system. The same `AnswerEngine` used in production
is used here — this is a black-box eval of the deployed system.

---

## Stage 3 — Judge LLM Prompt Design

The judge receives the question, reference answer, and RAG answer. It does **not**
see the retrieved chunks — it judges answer quality, not retrieval quality.

```
System:
You are an expert evaluator for a financial research AI system that answers
questions about SEC filings (10-K and 10-Q reports).

You will be given:
  - A question
  - A reference answer (written by an expert who read the source documents)
  - A candidate answer (generated by the AI system)

Score the candidate answer on a scale of 1–5:
  5 — Fully correct and complete; all key facts from the reference are present
      and no significant claims contradict the reference
  4 — Mostly correct; covers the main points with minor gaps or omissions
  3 — Partially correct; gets some facts right but misses important content
      or includes one clearly incorrect claim
  2 — Mostly incorrect or too vague to be useful; correct on surface framing
      but wrong on specifics
  1 — Factually wrong, completely off-topic, or refused to answer

Important: a candidate answer that uses different wording but conveys the same
facts as the reference should score 4 or 5. Do not penalise paraphrasing.
A candidate answer that adds extra correct detail beyond the reference should
not be penalised for that either.

Return ONLY valid JSON:
{"score": <int 1-5>, "reasoning": "<2-3 sentences>", "missing": "<key facts absent from candidate, or 'none'>"}

Question: {question}
Reference answer: {reference_answer}
Candidate answer: {rag_answer}
```

### Why include `missing`?

The `missing` field gives actionable diagnostic signal: if the judge consistently
reports the same type of missing content (e.g. "does not mention the IRA pricing
provision"), that points to a specific retrieval or prompt gap rather than a general
quality problem.

---

## File Layout

Note: the planned `evals/synthetic/` subdirectory was not used. Scripts are directly under `evals/` and data files are under `evals/data/`.

```
evals/
  build_test_set.py         — Stage 1: sample corpus, call Sampler LLM, write JSONL
  run_rag.py                — Stage 2: send questions to RAG, write rag_outputs.jsonl
  run_judge.py              — Stage 3: compare answers, write judge_results.jsonl
  run_synthetic_eval.py     — Orchestrator: runs all three stages end-to-end
  data/
    corpus_sample.json      — Which files were selected and why (audit trail)
    synthetic_test_set.jsonl
    rag_outputs.jsonl
    judge_results.jsonl
  results/
    summary.md
    <timestamp>.json
```

---

## Cost Estimate

| Stage | Model | Input | Est. cost |
|---|---|---|---|
| Sampler (72 batches × ~4k tokens) | GPT-4o | ~288k tokens | ~$1.15 |
| Sampler output (360 answers × ~200 tokens) | GPT-4o | ~72k tokens out | ~$1.08 |
| RAG generation (360 questions) | gpt-5.4-mini | ~540k tokens | ~$0.22 |
| Judge (360 comparisons × ~1k tokens) | Claude Sonnet | ~360k tokens | ~$1.08 |
| **Total** | | | **~$3.50** |

For a smaller initial run (72 files → 72 questions, one per batch):

| Stage | Est. cost |
|---|---|
| Sampler | ~$0.25 |
| RAG | ~$0.05 |
| Judge | ~$0.22 |
| **Total** | **~$0.52** |

---

## Scoring Targets

| Metric | Acceptable | Good |
|---|---|---|
| Mean judge score (1–5) | ≥ 3.5 | ≥ 4.2 |
| % answers scoring ≥ 4 | ≥ 60% | ≥ 80% |
| % answers scoring ≤ 2 | ≤ 15% | ≤ 5% |

Break down results by:
- **question_type** (risk vs financial vs regulatory vs comparative)
- **filing_type** (10-K vs 10-Q) — expect 10-Q to score lower
- **year** — flag if pre-2023 filings score significantly lower (potential
  embedding or retrieval staleness issue)
- **sector** — identify sectors where the RAG underperforms

---

## Limitations

**LLM-generated ground truth is not human-verified.** The sampler may generate
reference answers with subtle errors. Spot-check ~10% of Q&A pairs manually
before treating results as ground truth.

**No retrieval signal.** This pipeline measures end-to-end answer quality but
cannot distinguish bad retrieval from bad generation. Keep the existing Tier 2
retrieval metrics (precision/recall/MRR) for diagnosing retrieval-specific failures.

**Judge calibration drift.** Different judge models score differently on the same
scale. Fix the judge model across all runs so scores are comparable over time.
Document the judge model version in every results file.
