# Embedding Model Selection — Cost Analysis & Decision

## Corpus baseline

| Metric | Value |
|---|---|
| Chunks | 50,676 |
| Total characters | 83.7M |
| Estimated tokens | ~20M |

**Token methodology**: `words × 1.3` gives 18.6M tokens; `chars ÷ 4` gives 20.9M tokens. 20M is used as the conservative midpoint throughout. All costs below are one-time — the index is built once and reused at query time.

---

## Full model comparison

Pricing sourced from official provider pricing pages (see [Sources](#sources)).

| Model | Provider | $/1M tokens | **Embed cost** | Dim | Index size | Notes |
|---|---|---|---|---|---|---|
| `text-embedding-3-small` | OpenAI | $0.020 | **$0.40** | 1536 | 311 MB | Strong general quality; already in repo |
| `text-embedding-3-large` | OpenAI | $0.130 | $2.60 | 3072 | 623 MB | Highest OpenAI quality; large index |
| `text-embedding-ada-002` | OpenAI | $0.100 | $2.00 | 1536 | 311 MB | Legacy — worse quality than 3-small at 5× the cost |
| `text-embedding-005` | Google | $0.025 | $0.50 | 768 | 156 MB | Competitive price; smaller index |
| `embed-english-v3.0` | Cohere | $0.100 | $2.00 | 1024 | 208 MB | Strong retrieval benchmarks |
| `embed-english-light-v3.0` | Cohere | $0.100 | $2.00 | 384 | 78 MB | API price for local-model quality |
| `voyage-3-lite` | Voyage AI | $0.020 | **$0.40** | 512 | 104 MB | Budget Voyage option |
| `voyage-3` | Voyage AI | $0.060 | $1.20 | 1024 | 208 MB | Strong general retrieval |
| `voyage-finance-2` | Voyage AI | $0.120 | **$2.40** | 1024 | 208 MB | Finance-domain specialised ★ |
| `mistral-embed` | Mistral | $0.100 | $2.00 | 1024 | 208 MB | Multilingual capable |
| `all-MiniLM-L6-v2` | local | free | **$0** | 384 | 78 MB | Already in repo; baseline quality |
| `all-mpnet-base-v2` | local | free | **$0** | 768 | 156 MB | Better quality than MiniLM |
| `BAAI/bge-large-en-v1.5` | local | free | **$0** | 1024 | 208 MB | Top open-source retrieval model |
| `BAAI/bge-m3` | local | free | **$0** | 1024 | 208 MB | Dense + sparse; multilingual |

Approximate ChromaDB store size formula: `chunks × dim × 4 bytes (float32)` for the HNSW vector data, plus overhead for metadata.

---

## Models to avoid

**`text-embedding-ada-002`** — OpenAI's legacy model. It costs $2.00 (5× more than `text-embedding-3-small`) and scores lower on every published retrieval benchmark. There is no reason to use it for a new project.

**`embed-english-light-v3.0` (Cohere)** — charges full API pricing ($2.00) for a 384-d model that is no better than free local alternatives like `all-mpnet-base-v2`.

---

## Decision

### Selected model: `voyage-finance-2`

**Cost: $2.40 · Dimension: 1024 · Index: 208 MB**

The corpus consists entirely of SEC EDGAR filings — dense financial and regulatory text with domain-specific vocabulary (GAAP line items, safe-harbour language, segment reporting, MD&A constructs). Generic embedding models are trained on web text where this register is underrepresented. `voyage-finance-2` is explicitly trained on financial documents and consistently outperforms general models on financial information retrieval tasks.

According to Voyage AI's own evaluation across 11 finance-specific retrieval datasets, `voyage-finance-2` achieves an average of **+7% over OpenAI** (`text-embedding-3-large`) and **+12% over Cohere** (`embed-english-v3.0`) on NDCG@10. It also supports a 32K context window, much larger than the 8K limit of OpenAI and Mistral models and the 512-token limit of Cohere v3. [[1]](#sources)

For a graded assignment where answer precision over financial filings is the evaluation criterion, a finance-domain embedder is the highest-confidence choice. The $2.40 one-time cost is negligible relative to that benefit.

**Fallback: `text-embedding-3-small` ($0.40)**

If no API key is available or cost is a concern, `text-embedding-3-small` is the best general-purpose alternative. It is already integrated into the codebase as the default `openai` backend in `src/pipeline/embed.py`.

**Free fallback: `BAAI/bge-large-en-v1.5` ($0)**

The strongest free option. Scores 64.23 average / 54.29 retrieval on the MTEB benchmark (56 datasets), ranking among the top open-source retrieval models. [[2]](#sources) [[3]](#sources) Requires ~10–20 minutes on CPU to embed the full corpus but that is a one-time cost. Not yet wired into `src/pipeline/embed.py` as a named option; the `--model local` backend uses `all-MiniLM-L6-v2`.

---

## Query-time cost

Embedding one question costs a single API call (1 vector):

| Model | Query embed cost |
|---|---|
| `voyage-finance-2` | ~$0.000120 / query (billed at $0.12/1M) |
| `text-embedding-3-small` | ~$0.000020 / query |
| Local models | $0 |

At 10,000 queries the query-side cost is $1.20 (`voyage-finance-2`) or $0.20 (`text-embedding-3-small`). Negligible in both cases.

---

## Implementation notes

`src/pipeline/embed.py` currently supports `openai` (text-embedding-3-small) and `local` (all-MiniLM-L6-v2) backends. To use `voyage-finance-2`:

```bash
pip install voyageai
export VOYAGE_API_KEY=...
```

Then extend `src/pipeline/embed.py` with a `voyage` backend following the same pattern as the `openai` backend (`--model voyage`). `src/retrieval/retrieve.py`'s embedder selection would need a corresponding branch.

> **Important**: the model used at embed time must match the model used at query time. Mixing models silently degrades retrieval quality. With ChromaDB the collection does not encode dimension metadata externally, so the model name should be recorded in `contextualized_chunks.db`'s `meta` table (which already tracks `model`) to prevent accidental mismatches after rebuilds.

---

## Sources

Pricing pages were checked in May 2026. Prices are subject to change.

**Benchmarks and model claims**

1. Voyage AI — "Domain-Specific Embeddings: Finance Edition (voyage-finance-2)"  
   <https://blog.voyageai.com/2024/06/03/domain-specific-embeddings-finance-edition-voyage-finance-2/>

2. BAAI/bge-large-en-v1.5 model card (Hugging Face)  
   <https://huggingface.co/BAAI/bge-large-en-v1.5>

3. MTEB Leaderboard (Hugging Face)  
   <https://huggingface.co/spaces/mteb/leaderboard>

**Pricing pages**

- OpenAI: <https://openai.com/api/pricing/>
- Voyage AI: <https://docs.voyageai.com/docs/pricing>
- Cohere: <https://cohere.com/pricing>
- Google Vertex AI (embeddings): <https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings>
- Mistral: <https://mistral.ai/pricing/>
