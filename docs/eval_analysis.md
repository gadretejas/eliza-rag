## Status: Implemented

This document records results from the first full synthetic evaluation run (20260515_101548). A second run (20260517_092638) has since been completed; its results are in `evals/results/20260517_092638.json`. The mitigation steps described in `docs/eval_mitigation_plan.md` were applied between runs.

---

# RAG Evaluation Analysis — Run 20260515_101548

## Overview

The synthetic evaluation ran 160 judge-scored Q&A pairs across 9 sectors, 5 question types, and filing years 2015–2026. The judge LLM scored each RAG answer 1–5 for correctness and completeness against a reference answer generated from the source filing.

| Metric | Value | Target | Status |
|---|---|---|---|
| Questions evaluated | 160 | — | — |
| Mean judge score | 3.469 / 5.0 | ≥ 3.5 | ✗ BELOW |
| % scoring ≥ 4 | 60.6% | ≥ 60% | ✓ MET |
| % scoring ≤ 2 | 29.4% | ≤ 15% | ✗ BELOW |

The system **meets the ≥4 rate target** (60.6% vs 60%) but the mean is dragged down by a concentrated cluster of failures, and the ≤2 rate is nearly double the target. This is not broad mediocrity — the system performs well on the majority of questions and fails predictably on a specific subset.

---

## Score Distribution

| Score | Count | % |
|---|---|---|
| 5 — Fully correct | 37 | 23.1% |
| 4 — Mostly correct | 60 | 37.5% |
| 3 — Partially correct | 16 | 10.0% |
| 2 — Mostly incorrect / vague | 35 | 21.9% |
| 1 — Factually wrong / refused | 12 | 7.5% |

97 of 160 questions (60.6%) scored 4 or 5. The 47 low-scorers (1–2) are the focus of this analysis.

---

## By Sector

| Sector | Mean | n | Low (≤2) | High (≥4) | Low Rate |
|---|---|---|---|---|---|
| Industrial_Defense | 4.067 | 15 | 1 | 11 | 6.7% |
| Healthcare_Pharma | 3.750 | 20 | 4 | 15 | 20.0% |
| Financial_Banking | 3.550 | 20 | 6 | 14 | 30.0% |
| Consumer_Retail | 3.550 | 20 | 5 | 12 | 25.0% |
| Technology | 3.400 | 20 | 5 | 12 | 25.0% |
| Telecom | 3.400 | 5 | 2 | 3 | 40.0% |
| Automotive | 3.350 | 20 | 8 | 11 | 40.0% |
| Media_Entertainment | 3.150 | 20 | 8 | 11 | 40.0% |
| Energy | 3.100 | 20 | 8 | 8 | 40.0% |

**Industrial_Defense is the standout performer** (mean 4.07, only 1 low-scorer). Questions there tend to be narrative-heavy (program descriptions, government dependency, F-35 risk) where the retriever's semantic search excels. The four worst sectors — Energy, Media_Entertainment, Automotive, and Telecom — all hit a 40% low-scorer rate, driven by a high proportion of comparative and financial-table questions that expose retrieval gaps.

---

## By Question Type

| Type | Mean | n | Low (≤2) | High (≥4) | Low Rate |
|---|---|---|---|---|---|
| risk | 4.136 | 44 | 3 | 39 | 6.8% |
| operational | 3.694 | 36 | 8 | 23 | 22.2% |
| regulatory | 3.474 | 19 | 5 | 13 | 26.3% |
| financial | 3.107 | 28 | 12 | 12 | 42.9% |
| comparative | 2.636 | 33 | 19 | 10 | 57.6% |

**Risk questions are the strongest signal** — 88.6% score 4 or 5. Risk factors appear prominently in narrative sections that chunk well and match semantically to natural-language queries. **Comparative and financial questions are the dominant failure modes**, together accounting for 31 of the 47 low-scorers.

---

## By Filing Year

| Year | Mean | n | Low (≤2) | High (≥4) |
|---|---|---|---|---|
| 2015 | 4.000 | 3 | 1 | 2 |
| 2022 | 2.667 | 24 | 15 | 8 |
| 2023 | 3.226 | 31 | 11 | 17 |
| 2024 | 3.656 | 32 | 6 | 22 |
| 2025 | 3.636 | 44 | 10 | 31 |
| 2026 | 3.923 | 26 | 4 | 17 |

**2022 is a severe outlier** — mean 2.667, 62.5% low-scorer rate. This is not because older filings are harder; it is a direct consequence of comparative questions that pair a 2022 filing with a recent one. When the retriever must choose between two filings semantically, the more recent filing consistently wins all 15 retrieval slots. The 2022 filing ends up unrepresented, and the RAG system correctly reports it cannot compare.

---

## Failure Mode Analysis

### Summary

| Failure category | Items | Low-scoring | Description |
|---|---|---|---|
| Wrong emphasis (chunks fetched, wrong section) | 32 | 32 | Correct filing retrieved, wrong part of it |
| Missing second filing in comparatives | 8 | 7 | Retriever fills all slots from one filing |
| Retrieval miss (relevant chunks not found) | 5 | 5 | Specific content simply not retrieved |
| Boilerplate section not indexed | 3 | 3 | Exhibit lists, disclosure controls, Rule 10b5-1 |
| Correct (scored ≥ 3) | 112 | 0 | — |

**n_chunks is not correlated with score** — low-scorers average 13.9 chunks and high-scorers average 14.0. The problem is *which* chunks are retrieved, not *how many*.

---

### Failure Mode 1: Wrong Section Within the Correct Filing (32 items)

The retriever fetches the right company and filing but lands on a semantically adjacent section rather than the one the question targets. Because SEC filings are long and many sections share vocabulary (all risk sections mention "material adverse effect", "business", "operations"), the query's emphasis signal gets diluted.

**Examples:**
- Meta user-risk question: retriever returns data-security chunks instead of user-engagement chunks. Both contain "users" and "risk" but the question asks about the engagement risk specifically.
- Apple Q1 2022 share-repurchase tranches: retriever returns six-month totals instead of three-month quarterly breakdown.
- McDonald's Q1 2023 share repurchase: retriever returns a dollar total ($578.4M) but the reference requires share counts and monthly tranches.

**Distribution of this failure:**

| Question type | Count |
|---|---|
| comparative | 12 |
| financial | 8 |
| operational | 5 |
| regulatory | 4 |
| risk | 3 |

**Highest-affected sectors:** Media_Entertainment (6), Technology (5), Energy (5), Automotive (5).

---

### Failure Mode 2: Missing Second Filing in Comparative Questions (8 items)

Comparative questions explicitly reference two source files. The hybrid retriever scores all 15 slots by descending similarity to the query — with no diversity constraint, the semantically closer filing fills most or all slots. The RAG system then correctly reports "I cannot compare because the second filing was not provided."

**Confirmed cases (RAG explicitly admits missing a filing):**

| ID | Source files | Score |
|---|---|---|
| synth_financia_JPM_2025_0060 | JPM_10Q_2025Q2 + BLK_10K_2024 | 1 |
| synth_media_en_DIS_2023_0080 | DIS_10Q_2023Q3 + DIS_10K_2024 | 2 |
| synth_consumer_KO_2023_0110 | KO_10K_2022Q4 + KO_10Q_2025Q1 | 1 |
| synth_energy_XOM_2023_0125 | XOM_10K_2022Q4 + XOM_10Q_2025Q1 | 2 |
| synth_automoti_TSLA_2023_0137 | TSLA_10Q_2023Q3 + TSLA_10Q_2025Q2 | 1 |
| synth_automoti_TSLA_2024_0144 | TSLA_10Q_2024Q2 + TSLA_10K_2025 | 1 |
| synth_automoti_TSLA_2022_0148 | TSLA_10Q_2022Q1 + TSLA_10K_2022 | 2 |
| synth_automoti_TSLA_2026_0155 | TSLA_10K_2026 + TSLA_10K_2024 | 2 |

Note: a further 13 comparative questions score 2 due to the same cause but the RAG answer was partially salvaged by coincidental overlap in retrieved content.

---

### Failure Mode 3: Retrieval Miss — Specific Content Not Found (5 items)

Questions ask about narrow, specific facts that exist in the filing but the retriever does not surface. Common examples: exact workforce headcount figures (22,473 employees, 32 countries), business segment realignment details, and precise quarterly medical cost driver descriptions.

These questions are retrieval failures not because the filing is absent from the corpus but because the relevant chunk either has low semantic similarity to the query or was merged into a larger chunk where the specific detail is buried.

---

### Failure Mode 4: Boilerplate Sections Not Indexed (3 items)

Questions about exhibit lists (Disney 2022 Q1), Rule 10b5-1 trading arrangements, and disclosure-controls certifications score 1. These sections (Part II Item 5, Item 9A) consist of boilerplate legal language and exhibit tables that are semantically distant from natural-language queries. Even when the content exists in the corpus, the current chunking strategy — which targets narrative sections — does not reliably surface them.

---

## What the High Scorers Have in Common

The 97 items scoring 4 or 5 share these characteristics:

- **Narrative-dense answers**: Risk factors, regulatory exposure, and competitive threats described in prose. These match well to semantic search.
- **Single-filing questions**: No need to balance retrieval across multiple documents.
- **Well-known entities mentioned explicitly in the question**: Company name + specific program/product name (e.g., "Merck Gardasil in China", "Pfizer Seagen acquisition") gives the retriever a strong signal.
- **Broad thematic scope**: "What commodity price risks does ExxonMobil identify?" covers a whole section; the retriever can succeed with any chunk from that section.

---

## Key Takeaways

1. The retrieval system works well for thematic, narrative questions (risk, operational). It fails when precision matters — specific tables, specific sections, or multi-filing coverage.

2. Comparative questions are structurally broken for any two-filing pair where one filing is semantically dominant. This is a retrieval architecture gap, not a content gap.

3. The 2022 year degradation is a symptom of this comparative retrieval problem, not evidence that older filings are harder.

4. n_chunks (12–15 per question) is irrelevant to quality. The bottleneck is chunk selection, not chunk count.

5. Fixing comparative retrieval diversity alone (ensuring both source filings are represented) would recover an estimated 8–13 low-scorers and push the mean from 3.47 toward ~3.8.
