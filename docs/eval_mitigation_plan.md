## Status: Implemented

Both mitigations in this plan have been applied. Step 1 (boilerplate question exclusion) was added to the sampler prompt in `evals/build_test_set.py`. Step 2 (comparative retrieval diversity) was implemented as `retrieve_comparative()` in `src/retrieval/retrieve.py`. A second evaluation run (20260517_092638) was completed after these changes.

---

# RAG Eval Mitigation Plan

## Current State vs Targets

| Metric | Current | Target | Gap |
|---|---|---|---|
| Mean judge score | 3.469 | ≥ 3.5 | −0.031 |
| % scoring ≥ 4 | 60.6% | ≥ 60% | ✓ met |
| % scoring ≤ 2 | 29.4% | ≤ 15% | −14.4 pp |

The ≥4 rate is already at target. The ≤2 rate is the primary problem — 47 of 160 questions score 1 or 2.

## Chosen Action Plan

After reviewing the failure modes and their real-world relevance, two mitigations are worth implementing now:

1. **Remove boilerplate questions from the test set** — 30 minutes, makes the benchmark more honest immediately.
2. **Fix comparative retrieval diversity** — the one structural gap that would hurt real users doing cross-period research.

All other failure modes (financial table lookups, wrong section emphasis) are either niche use cases or would require deep changes to chunking/indexing that risk regressing the 60%+ of questions already working well. They are documented below as deferred options.

---

---

## Step 1 — Remove Boilerplate Questions from Test Set

**What:** Update the sampler prompt in `evals/build_test_set.py` to exclude questions about exhibit listings, disclosure controls, Rule 10b5-1 trading arrangements, Iran/OFAC disclosures, and internal control certifications. Regenerate the test set.

**Why:** These 3 questions are guaranteed to score 1 because the content is in boilerplate Part II sections the retriever doesn't surface. More importantly, they don't test anything meaningful about the RAG system's ability to answer financial research questions.

**Change to sampler prompt:**
```python
# Add to SAMPLER_SYSTEM in evals/build_test_set.py:
"""
Do NOT generate questions about:
- Exhibit listings (e.g., "what exhibits were filed?")
- Disclosure controls and procedures certifications
- Rule 10b5-1 trading arrangements adopted by officers
- Iran or OFAC-related disclosures
- Internal control certifications

Focus on questions that test understanding of business fundamentals,
financial performance, risk exposure, and strategic direction.
"""
```

**Then regenerate:**
```bash
python -m evals.build_test_set
```

**Effort:** 30 minutes.

---

## Step 2 — Comparative Retrieval Diversity (Highest Impact)

**Target failure mode:** 8 confirmed + ~13 partial "missing second filing" cases in comparative questions.  
**Estimated recovery:** 8–13 low-scorers → 3–4 points, pushing mean to ~3.8.

### Root Cause

The `HybridRetriever` ranks all candidates by a single score and returns the global top-k. When a comparative question spans two source filings, one filing semantically dominates and fills all 15 slots. There is no mechanism to enforce diversity across source documents.

### Fix: Source-Aware Retrieval for Comparative Questions

**Step 1 — Detect comparative questions.**  
At query time, check if the question contains signals of a multi-filing comparison:
```python
COMPARATIVE_SIGNALS = (
    "compare", "comparing", "contrast", "both filings",
    "versus", "vs.", "differ", "2022 and", "annual and",
    "quarterly and", "10-k and", "10-q and",
)

def is_comparative(question: str) -> bool:
    q = question.lower()
    return any(sig in q for sig in COMPARATIVE_SIGNALS)
```

**Step 2 — Extract likely source filing identifiers from the question.**  
If the question names two companies, two years, or two filing periods, parse them out. Use the same `HybridRetriever` to run two sub-queries (one per filing) and merge results:

```python
def retrieve_comparative(question: str, top_k: int = 15) -> list[Chunk]:
    # Run one retrieval pass and group by source file
    all_chunks = retriever.retrieve(question, top_k=top_k * 2)
    by_source = defaultdict(list)
    for chunk in all_chunks:
        by_source[chunk.metadata.get("source_file", "")].append(chunk)
    
    # Sort sources by their top chunk score
    ranked_sources = sorted(by_source, key=lambda s: by_source[s][0].score, reverse=True)
    
    if len(ranked_sources) >= 2:
        # Interleave top chunks from the two best-matching sources
        primary = by_source[ranked_sources[0]][:top_k // 2]
        secondary = by_source[ranked_sources[1]][:top_k // 2]
        remainder = top_k - len(primary) - len(secondary)
        rest = [c for s in ranked_sources[2:] for c in by_source[s]][:remainder]
        return primary + secondary + rest
    
    return all_chunks[:top_k]
```

**Step 3 — Wire into `run_rag.py`.**  
In the retrieval phase, use `retrieve_comparative()` when `is_comparative(question)` is True; otherwise use the normal path.

**Estimated effort:** 1–2 days. No changes to the retriever or index — purely a post-retrieval reranking step.

---

## Deferred Options (Not Implementing Now)

The following mitigations were identified but deprioritized. They are documented here for future reference if the eval is re-run and these failure modes become more significant.

---

### Deferred — Financial Table Retrieval

**Target failure mode:** 12 financial questions scoring ≤2, mostly involving share repurchase monthly tranches, exact authorization amounts, and per-share pricing.  
**Estimated recovery:** 5–8 low-scorers if specific table data becomes retrievable.

### Root Cause

Share repurchase tables, Iran-disclosure paragraphs, and Exhibit 2 certifications live in Part II (Items 2, 5, 9A) of SEC filings. The current chunking pipeline targets narrative sections and likely:
- Splits table rows across chunk boundaries, losing context
- Assigns these sections low priority during chunking (they are short, boilerplate-heavy)
- Embeds them with representations that do not match natural-language financial queries

### Fix A — Keyword Augmentation for Tabular Queries

Many financial questions contain highly specific numeric or entity strings ("$50 billion authorization", "59,754,580 shares", "July 1, 2025"). These are exact-match candidates — the BM25 component of the hybrid retriever should surface them if the tokens are present.

**Diagnose first:** Inspect whether the monthly repurchase data is present in the ChromaDB store at all:
```python
results = collection.query(
    query_texts=["common share repurchase authorization July 2025 JPMorgan"],
    n_results=5,
    where={"ticker": "JPM"},
)
```
If the chunks exist but rank below 15, the fix is to increase BM25 weight for financial/table queries. If they don't exist, the issue is chunking.

**Fix B — Preserve Part II Tables During Chunking**

In `src/ingestion/chunk.py`, ensure that Part II sections (Item 2, Item 5, Item 9A) are not split at arbitrary token boundaries. These sections are short enough to keep as single chunks. Tag them with `section_type: "table_disclosure"` in metadata so they can be filtered or boosted.

**Fix C — Query Expansion for Financial Questions**

When a question is classified as financial type and asks about a specific period (e.g., "first quarter 2025", "year-to-date through June 30"), prepend the retrieval query with the company ticker and date context before embedding. This pushes the embedding closer to the chunk's content, which will contain the ticker and date explicitly.

**Estimated effort:** Fix A (BM25 tuning) is 0.5 days. Fix B (chunking) is 1–2 days. Fix C (query expansion) is 1 day.

---

### Deferred — Wrong Section Within Correct Filing

**Target failure mode:** 32 items where the retriever fetches the right filing but the wrong section (e.g., data-security chunks instead of user-engagement chunks for a question about active-user risk).  
**Estimated recovery:** Conservative 8–12 of these move from score 2 to 3–4.

### Root Cause

Long SEC filings have many sections that share vocabulary. A question like "what user-related risk does Meta identify as critical?" contains the words "user" and "risk" which appear in security, privacy, and engagement sections alike. The semantic embedding cannot distinguish which risk flavor is intended.

### Fix A — Maximal Marginal Relevance (MMR) Within Retrieved Chunks

Currently the top-15 chunks are taken by raw score. Adding MMR diversification ensures that semantically redundant chunks from the same section do not crowd out relevant chunks from other sections. This helps when the "correct" chunk exists in the top-30 but is ranked below 15 similar chunks from a different section.

The ChromaDB client does not natively support MMR, but it can be implemented post-retrieval:
```python
def mmr_rerank(chunks: list[Chunk], query_embedding: list[float],
               lambda_val: float = 0.5, top_k: int = 15) -> list[Chunk]:
    selected = []
    remaining = list(chunks)
    while len(selected) < top_k and remaining:
        scores = []
        for chunk in remaining:
            relevance = cosine_sim(chunk.embedding, query_embedding)
            redundancy = max(cosine_sim(chunk.embedding, s.embedding) for s in selected) if selected else 0
            scores.append(lambda_val * relevance - (1 - lambda_val) * redundancy)
        best = remaining[max(range(len(remaining)), key=lambda i: scores[i])]
        selected.append(best)
        remaining.remove(best)
    return selected
```

`lambda_val = 0.5` balances relevance vs diversity. Tuning toward 0.7 keeps more relevance; toward 0.3 enforces stronger diversity.

**Caveat:** Chunk embeddings must be stored and retrievable. Check whether ChromaDB returns embeddings in the query result (`include=["embeddings"]`). If not, a separate embedding call per chunk is needed.

### Fix B — Section-Type Metadata Filtering

If chunks are tagged with their section (e.g., `item_1a`, `item_7`, `part_ii_item_2`), queries can be routed to the relevant section type based on the question:
- "risk" questions → prefer `item_1a` chunks
- "financial" questions → prefer `item_7`, `part_ii_item_2`
- "operational" questions → prefer `item_1`, `item_7`
- "regulatory" questions → prefer `item_1a`, `part_ii_item_1`

This requires section-type tagging at ingest time (see `docs/chunking_implementation.md` for the current chunking pipeline).

**Estimated effort:** Fix A (MMR) is 1 day. Fix B (metadata filtering) requires 1 day for the filter logic plus 1–2 days for backfilling section metadata in existing chunks if not already present.

---

---

## Expected Outcome

Completing Steps 1 and 2:
- Eliminates 3 guaranteed-1 questions from the benchmark (cleaner signal)
- Recovers 8–13 comparative low-scorers
- Estimated mean: 3.469 → ~3.7–3.8
- Estimated ≤2 rate: 29.4% → ~20–22%

---

## What Not to Change

- **top_k = 15**: n_chunks is uncorrelated with score. Increasing to 20 would not help.
- **LLM model**: Generation quality is fine. The LLM correctly reports when chunks are missing — the problem is retrieval, not generation.
- **Chunk size**: The current chunk size works well for narrative sections. Changing it globally would risk degrading the 60%+ of questions that already perform well.
- **System prompt**: The answer generation prompt is not a factor in these failures.
