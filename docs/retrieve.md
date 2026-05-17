# retrieve.py — Hybrid Retriever

Located at `src/retrieval/retrieve.py`. Implements a single-shot retrieval pipeline over the ChromaDB collection built by `src/pipeline/embed.py`. Given a natural-language question it returns the most relevant corpus chunks for the answer step.

The script moved from the project root to `src/retrieval/` as part of the restructure (see `docs/restructure_plan.md`). Import it as `from src.retrieval.retrieve import HybridRetriever, RetrieverConfig`.

Pipeline:

```
question → QueryRouter → metadata-filtered ANN search → cross-encoder re-rank
         → per-company balancing → top-k chunks
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
| `candidates_per_company` | `20` | ANN candidates fetched per mentioned ticker |
| `candidates_global` | `60` | ANN candidates when no ticker is mentioned |
| `oversample_factor` | `8` | Multiply `top_k` before metadata post-filter |
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

Converts a free-text question into structured filters with no LLM call.

```python
route = QueryRouter().route("What risks did Apple face in 2023?")
# RouteResult(tickers=['AAPL'], sections=['Item 1A'], date_from='2023-01-01', filing_type=None)
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

**Temporal extraction** — matches phrases like `"last year"`, `"recently"`, `"past two years"`, or an explicit 4-digit year to produce an ISO-8601 `date_from` cutoff.

| Phrase | Lookback |
|---|---|
| last year / recently / latest | 365 days |
| this year / current | 180 days |
| last two years | 730 days |
| last three years | 1095 days |
| "in 2023" / "since 2024" | Jan 1 of that year |

**Filing type** — returns `"10-K"` for `annual / 10-k / 10k` and `"10-Q"` for `quarterly / 10-q / 10q`; otherwise `None`.

---

### VectorIndex

Wraps a ChromaDB persistent client and collection. The collection is opened once at construction and kept open for the lifetime of the retriever.

```python
index = VectorIndex(chroma_path, collection_name)
results = index.search(query_vec, filters, top_k=20, oversample_factor=8)
# [(score, chunk_dict), ...]
```

**Search** retrieves `top_k × oversample_factor` ANN candidates via ChromaDB, then post-filters by metadata in Python. If fewer than `top_k // 2` chunks survive, two fallbacks are tried in order:

1. Relax `date_from` filter (keep ticker + section constraints)
2. Relax both `date_from` and `sections` (ticker constraint retained)

**Filter fields** accepted in the `filters` dict:

| Key | Type | Behaviour |
|---|---|---|
| `tickers` | `list[str]` | Include only these ticker symbols |
| `sections` | `list[str]` | Include only these Item IDs |
| `date_from` | `str` (ISO-8601) | Exclude filings before this date |
| `filing_type` | `str` | `"10-K"` or `"10-Q"` prefix match |
| `text_only` | `bool` | Exclude chunks where `content_type == "table"` |

Note: date filtering is applied in Python post-retrieval (not via ChromaDB `where`) because ChromaDB's `where` clause only supports numeric comparisons and filing dates are stored as ISO-8601 strings. See `docs/chromadb_migration.md`.

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
python retrieve.py "Tesla deliveries 2023" --reranker cohere
```

- Better accuracy on nuanced financial questions
- Costs ~$1 / 1M search units
- Scores normalised to [0, 1]

**No re-ranking** (`--no-rerank` or `reranker="none"`)

Candidates are returned sorted by raw ANN cosine similarity. Faster but less accurate for queries where semantic similarity does not capture relevance (e.g. a question about a specific number that appears in a different context).

---

### Per-company balancing (`_balance`)

When a question mentions multiple tickers, a greedy ANN search tends to over-represent the company whose filings are most similar to the query embedding. `_balance` corrects this:

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

**Question**: `"What risks did Apple and Tesla face in 2023?"`

1. **Route** → `tickers=['AAPL','TSLA']`, `sections=['Item 1A']`, `date_from='2023-01-01'`, `filing_type=None`

2. **Embed** → 1536-d (or 384-d) L2-normalised query vector

3. **ANN search** — two separate searches, one per ticker:
   - AAPL: top `20 × 8 = 160` ANN candidates, post-filter to 20 matching `{ticker=AAPL, section=Item 1A, date≥2023-01-01}`
   - TSLA: same → 20 chunks
   - Total candidates: 40

4. **Re-rank** — CrossEncoder scores all 40 (question, chunk) pairs; re-orders by relevance

5. **Balance** — `min_per_company = max(2, 15//2) = 7`; at least 7 AAPL and 7 TSLA chunks guaranteed; remaining slot filled by highest scorer

6. **Return** — 15 chunks, each with `score` field added, sorted by score

---

## Return format

Each chunk dict in the returned list has all fields from `chunks.jsonl` plus a `score` field:

```json
{
  "ticker":       "AAPL",
  "filing_type":  "10-K",
  "filing_date":  "2023-10-27",
  "section_id":   "Item 1A",
  "section_name": "Risk Factors",
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
| `n_candidates` | `int` | Chunks before re-ranking |
| `n_after_rerank` | `int` | Chunks after re-ranking (= `top_k`) |
| `final_chunks` | `list[dict]` | Returned chunks with scores |
| `scores` | `list[float]` | Scores in the same order as `final_chunks` |

---

## Failure modes and fallbacks

| Situation | Behaviour |
|---|---|
| ChromaDB collection not found | Hard exit with message: run `embed.py` first |
| ChromaDB collection empty | Hard exit with message: run `embed.py` first |
| No chunks pass filters (strict date) | Relax `date_from`, retry |
| Still too few after relaxing date | Relax `sections` too, retry |
| `OPENAI_API_KEY` not set (OpenAI embed model requested) | Falls back to local embedder |
| `sentence-transformers` not installed | Hard exit with install command |
| `COHERE_API_KEY` not set (cohere reranker) | Hard exit with clear message |

---

## Performance notes

| Component | Typical latency (CPU) |
|---|---|
| ChromaDB ANN search (50k vectors) | ~2 ms |
| Metadata post-filter (160 candidates) | <1 ms |
| Local cross-encoder re-rank (40 candidates) | ~30 ms |
| OpenAI query embedding | ~200 ms (network) |
| Local query embedding | ~15 ms |

End-to-end with local models: **~50 ms**. With OpenAI query embedding: **~250 ms**.

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
