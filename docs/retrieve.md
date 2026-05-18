# retrieve.py — Hybrid Retriever

Located at `src/retrieval/retrieve.py`. Implements a single-shot retrieval pipeline over the ChromaDB collection built by `src/pipeline/embed.py`. Given a natural-language question it returns the most relevant corpus chunks for the answer step.

The script moved from the project root to `src/retrieval/` as part of the restructure (see `docs/restructure_plan.md`). Import it as `from src.retrieval.retrieve import HybridRetriever, RetrieverConfig`.

Pipeline:

```
question → QueryRouter → date-aware ANN search → Python date filter
         → cross-encoder re-rank → per-company balancing → top-k chunks
```

---

## Usage

### As a library

```python
from src.retrieval.retrieve import HybridRetriever, RetrieverConfig

# Default config — local re-ranker, top 15 chunks
retriever = HybridRetriever()
results   = retriever.retrieve("What are NVDA's primary risk factors?")

for chunk in results:
    print(chunk["ticker"], chunk["section_id"], chunk["score"])
    print(chunk["text"][:300])
```

### With a custom config

```python
config = RetrieverConfig(
    top_k=10,
    reranker="cohere",   # requires COHERE_API_KEY
)
retriever = HybridRetriever(config)
results   = retriever.retrieve("Compare Apple and Microsoft revenue trends")
```

### Retrieval trace

```python
trace = retriever.retrieve_with_trace("What risks does Tesla face?")

print(trace.route.tickers)       # ['TSLA']
print(trace.route.sections)      # ['Item 1A']
print(trace.route.date_from)     # None (no temporal signal in question)
print(trace.n_candidates)        # chunks before re-ranking
print(trace.scores)              # final relevance scores
```

### CLI smoke-test

```bash
# Basic query
python -m src.retrieval.retrieve "What are Apple's biggest risk factors?"

# Show routing and score details
python -m src.retrieval.retrieve "What are Apple's biggest risk factors?" --trace

# More results, no re-ranking
python -m src.retrieval.retrieve "NVDA revenue growth" --top-k 20 --no-rerank

# Cohere re-ranker (requires COHERE_API_KEY)
python -m src.retrieval.retrieve "Tesla supply chain risks" --reranker cohere
```

---

## CLI arguments

| Argument | Default | Description |
|---|---|---|
| `question` | (required) | Natural-language question |
| `--top-k` | `15` | Number of chunks to return |
| `--no-rerank` | off | Skip re-ranking, sort by ANN score only |
| `--reranker` | `none` | Re-ranker backend: `local`, `cohere`, `none` |
| `--trace` | off | Print routing details and scores |

---

## Configuration — `RetrieverConfig`

All retriever behaviour is controlled by a `RetrieverConfig` dataclass. Pass one to `HybridRetriever(config=...)`.

| Field | Default | Description |
|---|---|---|
| `chroma_path` | from `src/config.py` | Path to the ChromaDB store directory |
| `chroma_collection` | from `src/config.py` | ChromaDB collection name |
| `candidates_per_company` | `35` | ANN candidates fetched per mentioned ticker (6× expansion when date-bounded) |
| `candidates_global` | `80` | ANN candidates when no ticker is mentioned (4× expansion when date-bounded) |
| `oversample_factor` | `8` | Multiply `top_k` before metadata post-filter inside ChromaDB |
| `rerank` | `True` | Enable cross-encoder re-ranking |
| `reranker` | `"none"` | Backend: `local`, `cohere`, or `none` |
| `reranker_model` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model (local backend) |
| `cohere_model` | `rerank-english-v3.0` | Cohere model name |
| `top_k` | `15` | Final chunks returned |
| `min_per_company` | `None` | Min chunks per ticker (auto: `max(2, top_k // n_companies)`) |
| `allowed_tickers` | `None` | RBAC corpus restriction; `None` = unrestricted |

---

## Components

### QueryRouter

Converts a free-text question into structured filters with a single lightweight LLM call (no separate model — uses the same provider configured for answers, via `src/answer/answer.py`'s router path).

```python
route = QueryRouter().route("What risks did Apple face in 2023?")
# RouteResult(tickers=['AAPL'], sections=['Item 1A'],
#             date_from='2023-01-01', date_to='2023-12-31', filing_type=None)
```

**Ticker extraction** — scans the lowercased question for 54 company aliases. Aliases are matched longest-first so multi-word names (`jp morgan`) are never shadowed by shorter substrings (`morgan`). Returns deduplicated canonical tickers sorted alphabetically.

**Section routing** — matches signal keywords to Item IDs via `_SECTION_SIGNALS`:

| Keywords (sample) | Mapped sections |
|---|---|
| risk, risks, exposure, threat, hazard | Item 1A |
| revenue, earnings, margin, cash flow, EPS | Item 7, Item 8 |
| regulatory, compliance, litigation, FDA | Item 1A, Item 1 |
| business, products, segment, competition | Item 1 |
| management, MDA, liquidity, capital allocation | Item 7 |

If no keyword matches, defaults to `[Item 1A, Item 1, Item 7]`.

**Temporal extraction** — matches phrases like `"last year"`, `"recently"`, `"past two years"`, or an explicit 4-digit year to produce an ISO-8601 `date_from` cutoff. All relative phrases are anchored to `date.today()` at call time.

| Phrase | `date_from` | `date_to` |
|---|---|---|
| last year / recently / latest | today − 365 days | None |
| this year / current | today − 180 days | None |
| last two years | today − 730 days | None |
| last three years | today − 1095 days | None |
| "in 2023" / "fiscal 2023" | 2023-01-01 | 2023-12-31 |
| "since 2024" | 2024-01-01 | None |
| no temporal signal | None | None |

**Filing type** — returns `"10-K"` for `annual / 10-k / 10k` and `"10-Q"` for `quarterly / 10-q / 10q`; otherwise `None`.

---

### VectorIndex

Wraps a ChromaDB persistent client and collection. The collection is opened once at construction and kept open for the lifetime of the retriever.

```python
index = VectorIndex(chroma_path, collection_name)
results = index.search(query_vec, filters, top_k=35, oversample_factor=8)
# [(score, chunk_dict), ...]
```

**Search** retrieves `top_k × oversample_factor` ANN candidates via ChromaDB, then post-filters by metadata in Python. If fewer than `top_k // 2` chunks survive the section filter, two fallbacks are tried in order:

1. Relax section constraints (keep ticker constraint)
2. No filter at all (last resort)

**Date filtering is not applied inside ChromaDB** because ChromaDB's `where` clause only supports numeric operands, and filing dates are stored as ISO-8601 strings. Date filtering happens in Python after retrieval — see `_apply_date_filter` below.

**Filter fields** accepted in the `filters` dict:

| Key | Type | Behaviour |
|---|---|---|
| `tickers` | `list[str]` | Include only these ticker symbols |
| `sections` | `list[str]` | Include only these Item IDs |
| `date_from` | `str` (ISO-8601) | Python post-filter lower bound (not a ChromaDB filter) |
| `date_to` | `str` (ISO-8601) | Python post-filter upper bound (not a ChromaDB filter) |
| `filing_type` | `str` | `"10-K"` or `"10-Q"` prefix match |
| `text_only` | `bool` | Exclude chunks where `content_type == "table"` |

---

### Date-Aware Candidate Expansion

This is the most important correctness feature for temporal queries.

**The problem**: older filings can have 3–4× more chunks in financial sections (Item 2 had 26–32 chunks in 2022 NVDA filings; recent filings have only 8–10). A pure semantic search returns the top-N most similar chunks, and those are systematically biased toward older, more verbose filings even when the question explicitly asks about recent data.

**The fix**: when `date_from` or `date_to` is set in the route, the retriever requests many more candidates from the index before applying the Python date filter:

```python
search_k_per_company = cfg.candidates_per_company       # 35 by default
search_k_global      = cfg.candidates_global            # 80 by default
if route.date_from or route.date_to:
    search_k_per_company = min(search_k_per_company * 6, 300)   # up to 210
    search_k_global      = min(search_k_global * 4, 500)        # up to 320
```

With 210 candidates per company, recent chunks that rank lower on pure semantic similarity (because the filing is shorter) are still included in the pool and can be selected by the date filter.

---

### Python Date Filtering (`_apply_date_filter` / `_apply_date_penalty`)

After collecting candidates from ChromaDB, date filtering is applied in Python:

```python
filtered = _apply_date_filter(candidates, route.date_from, route.date_to)
if len(filtered) >= max(1, cfg.top_k // 3):   # ≥5 results
    candidates = filtered                        # hard filter: drop out-of-window chunks
else:
    candidates = _apply_date_penalty(candidates, route.date_from, route.date_to, penalty=0.40)
```

**Hard filter** (`_apply_date_filter`): drops all chunks outside the date window. Applied when at least `top_k // 3` (≥5) in-window chunks exist.

**Soft penalty** (`_apply_date_penalty`): multiplies out-of-window chunk scores by `0.40`. Applied only when in-window chunks are very sparse (< 5). A 0.40× penalty means an out-of-window chunk needs a raw semantic score more than 2.5× higher than an in-window chunk to survive — in practice this nearly always produces an all-in-window result even in sparse cases.

The threshold `top_k // 3` (rather than the more lenient `top_k // 2`) ensures the hard filter is applied in the common case. Lowering this threshold reduces the chance of falling back to the penalty path.

---

### Recency Preference (`_apply_recency_preference`)

Applied **only** when the question has no explicit date signal (`date_from` and `date_to` are both `None`). Gently boosts newer filings to avoid the system defaulting to the oldest available filing when multiple filings are equally relevant.

```python
score *= 0.95 ** years_old   # 0.95 per year of age, anchored to date.today()
```

A 3-year-old chunk needs a raw score ~15% higher than a current chunk to beat it. This avoids stale-data answers on undated questions without overriding clearly more relevant older content.

---

### Reranker

Cross-encoder that scores each (question, chunk_text) pair and re-orders candidates by relevance. Model is lazy-loaded on first call.

**Local backend** (`reranker="local"`)

Uses `sentence-transformers` `CrossEncoder`. Default model: `cross-encoder/ms-marco-MiniLM-L-6-v2`.

- No API key required
- ~30ms per 60-candidate batch on CPU
- Scores are raw logits; higher = more relevant

**Cohere backend** (`reranker="cohere"`)

Uses the Cohere v2 Rerank API. Requires `COHERE_API_KEY` environment variable.

```bash
export COHERE_API_KEY=...
python -m src.retrieval.retrieve "Tesla deliveries 2023" --reranker cohere
```

- Better accuracy on nuanced financial questions
- Costs ~$1 / 1M search units
- Scores normalised to [0, 1]

**No re-ranking** (`--no-rerank` or `reranker="none"`)

Candidates are returned sorted by raw ANN cosine similarity. Faster but less accurate for queries where semantic similarity does not capture relevance (e.g. a question about a specific number that appears in a different context).

---

### Per-company balancing (`_balance`)

When a question mentions multiple tickers, a global top-k after re-ranking tends to over-represent the company whose filings are most similar to the query embedding. `_balance` corrects this:

1. Reserve `min_per_company` slots for each mentioned ticker, filled from the re-ranked list in score order.
2. Fill remaining `top_k - reserved` slots with the highest-scored chunks across all companies.
3. Re-sort the full result set by score descending.

`min_per_company` defaults to `max(2, top_k // n_companies)`. For a 3-company comparison with `top_k=15` this gives 5 chunks per company.

---

### Embedder auto-detection

`HybridRetriever` selects the query embedder based on whether `OPENAI_API_KEY` is set:

| Condition | Embedder |
|---|---|
| `OPENAI_API_KEY` set | `text-embedding-3-small` via OpenAI API |
| No API key | `all-MiniLM-L6-v2` via sentence-transformers |

The embedder used at query time must match the model used at index-build time. The ChromaDB collection must be rebuilt with `src/pipeline/embed.py` if you switch embedding models.

---

## Full pipeline walkthrough

**Question**: `"How has NVIDIA's revenue changed over the last two years?"`

1. **Route** → `tickers=['NVDA']`, `sections=['Item 2', 'Item 7', 'Item 8']`, `date_from='2024-05-17'` (today − 730 days), `date_to=None`, `filing_type=None`

2. **Embed** → 1536-d (or 384-d) L2-normalised query vector

3. **Date-aware ANN search** — date window is active, so candidate count is expanded:
   - `search_k = min(35 × 6, 300) = 210`
   - ChromaDB returns top-210 NVDA chunks from Item 2/7/8, ranked by semantic similarity
   - Without expansion, the top-35 would all be from 2022–2023 (older filings had 26–32 Item 2 chunks vs 8–10 for recent filings)
   - With 210 candidates, all 233 NVDA Item 2/7/8 chunks are included, ensuring recent filings appear in the pool

4. **Python date filter** — `_apply_date_filter` retains only chunks with `filing_date ≥ 2024-05-17`. Result: ~58 chunks from 7 NVDA filings (2024-05 to 2025-11). Since 58 ≥ 5 (`top_k // 3`), the hard filter is applied — all 2022–2023 chunks are dropped.

5. **Re-rank** — CrossEncoder scores all 58 (question, chunk) pairs; top-15 selected

6. **No balancing** — single ticker, so `_balance` is skipped; top-15 by score returned directly

7. **Return** — 15 chunks, all from 2024-05+, each with `score` field added

---

**Question**: `"What are Apple's main revenue segments?"` (no date signal)

1. **Route** → `tickers=['AAPL']`, `sections=['Item 7', 'Item 8']`, `date_from=None`, `date_to=None`

2. **ANN search** — no date expansion: `search_k = 35`

3. **No date filter** — `_apply_date_filter` returns all candidates unchanged

4. **Recency preference** — `_apply_recency_preference` applies `0.95^years_old` to gently prefer newer filings

5. **Re-rank → return top-15**

---

## Return format

Each chunk dict in the returned list has all fields from `chunks.jsonl` plus a `score` field:

```json
{
  "ticker":       "NVDA",
  "filing_type":  "10-Q",
  "filing_date":  "2025-08-27",
  "section_id":   "Item 2",
  "section_name": "Management's Discussion and Analysis",
  "content_type": "text",
  "text":         "...",
  "score":        0.8231
}
```

`score` is the cross-encoder logit (local) or relevance score in [0,1] (Cohere) after re-ranking, or the raw cosine similarity if re-ranking is disabled.

---

## `RetrievalTrace` fields

| Field | Type | Description |
|---|---|---|
| `question` | `str` | Original question |
| `route` | `RouteResult` | Structured filters derived from the question |
| `n_candidates` | `int` | Chunks entering the re-ranker (after date filter) |
| `n_after_rerank` | `int` | Chunks after re-ranking (= `top_k`) |
| `final_chunks` | `list[dict]` | Returned chunks with scores |
| `scores` | `list[float]` | Scores in the same order as `final_chunks` |

---

## Failure modes and fallbacks

| Situation | Behaviour |
|---|---|
| ChromaDB collection not found | Hard exit with message: run `embed.py` first |
| ChromaDB collection empty | Hard exit with message: run `embed.py` first |
| Fewer than `top_k // 3` chunks in date window | Apply 0.40× penalty to out-of-window chunks instead of hard cut |
| No chunks match ticker + section filter | Retry with section filter relaxed; then no filter at all |
| `OPENAI_API_KEY` not set (OpenAI embed model requested) | Falls back to local embedder |
| `sentence-transformers` not installed | Hard exit with install command |
| `COHERE_API_KEY` not set (cohere reranker) | Hard exit with clear message |

---

## Performance notes

| Component | Typical latency (CPU) |
|---|---|
| ChromaDB ANN search, 35 candidates | ~2 ms |
| ChromaDB ANN search, 210 candidates (date-bounded query) | ~5 ms |
| Python date filter (210 candidates) | <1 ms |
| Local cross-encoder re-rank (60 candidates) | ~30 ms |
| OpenAI query embedding | ~200 ms (network) |
| Local query embedding | ~15 ms |

End-to-end with local models: **~50 ms** (undated query), **~55 ms** (date-bounded query). With OpenAI query embedding: **~250–255 ms**.

---

## Dependencies

All required. Install with `pip install -r requirements.txt`.

| Package | Use |
|---|---|
| `chromadb` | Vector store |
| `numpy` | Vector arithmetic |
| `sentence-transformers` | Local re-ranker + local embedder |
| `openai` | OpenAI query embedder (if using OpenAI embedding model) |
| `cohere` | Cohere re-ranker (optional) |
