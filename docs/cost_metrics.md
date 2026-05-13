# Cost Metrics

All costs are one-time unless noted. Once an artifact is generated it is reused indefinitely.

---

## Contextualization (`contextualize.py`)

### Measured test run

| Metric | Value |
|---|---|
| Documents tested | 2 (AAPL, NVDA — latest 10-K each) |
| Calls made | 49 (25 AAPL + 24 NVDA) |
| Model | `gpt-5.4-mini` |
| Actual cost | **$0.04** |
| Cost per call | $0.00082 |

### Full corpus extrapolation

| Metric | Value |
|---|---|
| Document contexts | 246 |
| Section contexts | 2,736 |
| Total calls | 2,982 |
| **Estimated cost** | **~$2.43** |

The full corpus estimate is extrapolated directly from the measured $0.04 test cost rather than theoretical token counts — actual cost per call came in lower than the $3.29 theoretical estimate in [contextualization.md](contextualization.md) because real prompts used fewer tokens than the assumed maximum.

> **Important:** `contextualized_chunks.db` is generated once and reused. Re-embedding the corpus with a different embedding model costs nothing extra on the LLM side.

---

## Embedding (`embed.py`)

| Model | Cost |
|---|---|
| `text-embedding-3-small` (OpenAI) | ~$0.40 |
| `all-MiniLM-L6-v2` (local) | free |
| `voyage-finance-2` (recommended) | ~$2.40 |

Full analysis and model comparison in [embedding_models.md](embedding_models.md).

---

## Answer generation (`answer.py`)

Cost per query at typical prompt size (~8,000 input tokens, ~400 output tokens):

| Model | Cost per query | Cost at 1,000 queries |
|---|---|---|
| `gpt-5.4-mini` (default) | ~$0.008 | ~$8 |
| `gpt-5.4` | ~$0.026 | ~$26 |
| `gpt-5.5` | ~$0.052 | ~$52 |
| Ollama (local) | $0 | $0 |

---

## Total one-time setup cost

| Step | Model | Cost |
|---|---|---|
| Contextualization | `gpt-5.4-mini` | ~$2.43 |
| Embedding | `voyage-finance-2` | ~$2.40 |
| **Total** | | **~$4.83** |

Query costs are ongoing and model-dependent (see answer generation table above).
