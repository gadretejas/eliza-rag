# RAG Evaluation Plan

## Overview

A RAG system has two independently fail-able components: **retrieval** and **generation**. A
perfect answer from bad chunks is luck; perfect chunks with a bad prompt still fail. Evaluation
must cover both layers. ROUGE and related metrics live in the generation layer — they measure
lexical overlap between a generated answer and a human reference. This plan covers four
evaluation tiers arranged by what they measure and how much work they require.

---

## Tier 1 — Ground-truth answer metrics (ROUGE, BERTScore, METEOR)

These metrics compare a generated answer against a human-written reference answer using the same
question. They require a **gold dataset** of (question, reference answer) pairs.

### Metrics

| Metric | What it measures | Strength | Weakness |
|---|---|---|---|
| **ROUGE-1** | Unigram recall/precision/F1 against reference | Simple, fast, interpretable | Sensitive to wording, ignores meaning |
| **ROUGE-2** | Bigram overlap | Captures short phrases | Still purely lexical |
| **ROUGE-L** | Longest common subsequence F1 | Order-aware | Can reward unrelated text |
| **BERTScore** | Cosine similarity of BERT token embeddings | Semantic — "revenue" ≈ "income" | Slower, needs GPU or API |
| **METEOR** | Unigram F1 with stemming + synonym matching | Better than ROUGE for paraphrases | Requires WordNet |

ROUGE-1 and ROUGE-2 F1 are the primary signals. BERTScore is the semantic sanity-check when
ROUGE is low but the answer looks correct.

### Gold dataset construction

A set of ~60–80 manually curated examples covering:

| Category | # examples | Notes |
|---|---|---|
| Single-company risk factors | 20 | e.g. "What are TSLA's primary risk factors?" |
| Cross-company comparison | 10 | e.g. "Compare Apple and JPMorgan risk" |
| Financial metrics | 15 | e.g. "NVDA revenue growth last two years" |
| Sector-level | 10 | e.g. "Regulatory risks facing pharma companies" |
| Time-specific | 10 | e.g. "What risks did MSFT highlight in its 2024 10-K?" |
| Adversarial (out of corpus) | 5 | Questions the corpus cannot answer |

For each question, a human writes a short reference answer (3–6 sentences) drawn directly from
the filing text. Reference answers should not be LLM-generated because they would bias the
evaluation in favour of the model being tested.

### Scoring targets

| Metric | Acceptable | Good |
|---|---|---|
| ROUGE-1 F1 | ≥ 0.35 | ≥ 0.50 |
| ROUGE-2 F1 | ≥ 0.15 | ≥ 0.25 |
| ROUGE-L F1 | ≥ 0.30 | ≥ 0.45 |
| BERTScore F1 | ≥ 0.85 | ≥ 0.90 |

Note: these thresholds are reasonable for open-ended financial QA; abstractive answers naturally
score lower than extractive ones on ROUGE.

---

## Tier 2 — Retrieval quality metrics

Before the LLM sees anything, the retriever must surface the right chunks. Bad retrieval cannot
be fixed downstream.

### Metrics

**Context Precision** — of the *k* retrieved chunks, what fraction are relevant to the question?

```
Context Precision = |relevant ∩ retrieved| / |retrieved|
```

**Context Recall** — of all chunks that *could* answer the question, what fraction were
retrieved?

```
Context Recall = |relevant ∩ retrieved| / |relevant|
```

**MRR (Mean Reciprocal Rank)** — how high does the first relevant chunk appear in the ranked
list? Useful for checking whether good chunks are near the top.

```
MRR = mean(1 / rank_of_first_relevant_chunk)
```

### Annotation approach

For each gold question, annotate which source files / chunk IDs are the "correct" sources (can
be read off from the reference answer's citations). The retriever is then run and the returned
chunk set is compared against the annotated set.

A chunk is "relevant" if it contains the passage cited in the reference answer, identified by
file name + section ID.

### Scoring targets

| Metric | Acceptable | Good |
|---|---|---|
| Context Precision@15 | ≥ 0.40 | ≥ 0.60 |
| Context Recall@15 | ≥ 0.60 | ≥ 0.80 |
| MRR | ≥ 0.50 | ≥ 0.70 |

---

## Tier 3 — Faithfulness (no hallucination)

ROUGE measures similarity to a reference. It does not check whether the answer is *grounded* in
the retrieved chunks. A model can score well on ROUGE by repeating the reference while still
adding hallucinated claims.

**Faithfulness** measures the fraction of claims in the generated answer that are supported by
the retrieved context.

### Approach: LLM-as-judge

For each generated answer, send the following to a cheap model (gpt-5.4-mini):

```
System: You are a fact-checker. Given a context and an answer, identify each
factual claim in the answer and determine whether it is directly supported by
the context. Return JSON: {"supported": int, "unsupported": int, "score": float}
where score = supported / (supported + unsupported).

Context: {retrieved_chunks}
Answer: {generated_answer}
```

Faithfulness score = mean score across all eval questions.

**Target:** ≥ 0.90 (at most 1 in 10 claims unsupported).

### Alternative: citation coverage

A lighter proxy: compute the fraction of sentences in the answer that contain
at least one `[n]` citation marker. Fully grounded answers should cite every
substantive claim.

```
Citation coverage = sentences_with_citation / total_sentences
```

---

## Tier 4 — Answer relevance

Does the answer actually address the question? A model can be faithful (only says things in the
context) while completely ignoring what was asked.

### Approach: LLM-as-judge

```
System: Rate how well this answer addresses the question on a scale of 1–5.
5 = fully answers the question, 1 = completely off-topic.
Return only the integer.

Question: {question}
Answer: {generated_answer}
```

Average score across the eval set.

**Target:** ≥ 4.0 / 5.0.

---

## Implementation

### Dependencies

```
rouge-score>=0.1.2    # ROUGE-1, ROUGE-2, ROUGE-L
bert-score>=0.3.13    # BERTScore
nltk>=3.8             # METEOR
pandas>=2.0           # results tables
```

### File layout

```
evals/
  gold_dataset.jsonl        # {question, reference_answer, source_files[]}
  run_eval.py               # orchestrates all tiers, writes results/
  metrics/
    rouge_eval.py           # Tier 1: ROUGE + BERTScore + METEOR
    retrieval_eval.py       # Tier 2: Precision, Recall, MRR
    faithfulness_eval.py    # Tier 3: LLM-as-judge
    relevance_eval.py       # Tier 4: LLM-as-judge
  results/
    <timestamp>.json        # full per-question breakdown
    summary.md              # aggregated table printed to terminal
```

### Gold dataset format

```jsonl
{
  "id": "risk_aapl_001",
  "question": "What are Apple's primary risk factors as of its most recent 10-K?",
  "reference_answer": "Apple faces several key risks including supply chain concentration ...",
  "source_files": ["AAPL_10K_2025-10-31_full.txt"],
  "source_sections": ["Item 1A"]
}
```

### `run_eval.py` flow

```
1. Load gold_dataset.jsonl
2. For each question:
   a. Call retrieve() → record chunks returned                (Tier 2)
   b. Call answer_stream() or answer() → record generated text
   c. Compare retrieved chunks vs gold source_files           (Tier 2 scoring)
   d. Compute ROUGE/BERTScore vs reference_answer             (Tier 1 scoring)
   e. Call LLM faithfulness judge                             (Tier 3)
   f. Call LLM relevance judge                                (Tier 4)
3. Aggregate and write results/
```

Step 2e/2f use a single batch call per question to keep eval costs low
(~$0.001 per question with gpt-5.4-mini → ~$0.08 for 80 questions).

---

## Limitations of ROUGE for this use case

ROUGE was designed for news summarisation where reference and hypothesis are
close in wording. For open-ended financial QA, several failure modes apply:

- **Paraphrase penalty**: "revenue increased 40%" scores zero overlap with "top
  line grew by forty percent" even though both are correct.
- **Length sensitivity**: ROUGE-2 rewards longer answers that share more bigrams
  with the reference, even if they contain extra irrelevant content.
- **Multi-reference gap**: a single reference answer written by one annotator may
  not capture all valid phrasings.

**Mitigation**: always report BERTScore alongside ROUGE and treat ROUGE below
threshold as a flag for manual review rather than an automatic failure.

---

## Suggested first sprint

1. Build `gold_dataset.jsonl` with 20 questions (5 per category above) — ~2 hours
2. Implement `retrieval_eval.py` and run Tier 2 — cheapest, no API cost
3. Implement `rouge_eval.py` and run Tier 1 — no API cost
4. Review worst-performing questions to identify whether failures are retrieval
   or generation problems before investing in Tier 3/4
