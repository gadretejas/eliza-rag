# Answer Generation — Design Document

## Overview

`answer.py` is the final stage of the RAG pipeline. It takes a natural-language question, retrieves relevant chunks via `HybridRetriever`, formats them as grounded context, calls an LLM, and returns a structured answer with traceable citations back to source filings.

```
question
   │
   ▼
HybridRetriever.retrieve()        ← retrieve.py
   │  top-k chunks with metadata
   ▼
build_prompt()                    ← formats numbered context block
   │  system prompt + context + question
   ▼
LLMClient.complete()              ← OpenAI API or Ollama
   │  raw answer text with [n] markers
   ▼
parse_citations()                 ← maps [n] → chunk metadata
   │
   ▼
Answer(text, citations, metadata)
```

---

## Goals

- Generate factual, grounded answers over SEC EDGAR filings
- Every claim traceable to a specific filing (ticker, date, section)
- Plug-and-play between local dev (Ollama) and production (OpenAI) with no code changes
- Structured citation output usable by a frontend for source previewing

## Non-goals

- No agentic multi-turn reasoning (deferred to `AgenticRetriever` — see `retrieval_design.md`)

---

## LLM backends

### Development — Ollama (local, free)

Ollama exposes an OpenAI-compatible REST API at `http://localhost:11434/v1`. The same `openai` SDK is used; only `base_url` and `api_key` (set to `"ollama"`) differ. No additional dependencies.

| Model | Pull command | Disk | Notes |
|---|---|---|---|
| `llama3.2` | `ollama pull llama3.2` | 2 GB | Default dev model — fast iteration |
| `llama3.1:8b` | `ollama pull llama3.1:8b` | 4.7 GB | Better reasoning; use for quality testing |
| `mistral` | `ollama pull mistral` | 4.1 GB | Strong instruction following |

### Production — OpenAI

| Model ID | $/1M input | $/1M output | Context | Role |
|---|---|---|---|---|
| `gpt-5.4-mini` | $0.75 | $4.50 | 400K | **Default prod** |
| `gpt-5.4` | $2.50 | $15.00 | 1M | High-quality option |
| `gpt-5.5` | $5.00 | $30.00 | 1M | Reserved for evaluation |

Pricing source: [developers.openai.com/docs/models](https://developers.openai.com/docs/models)

`gpt-5.4-mini` is the production default. The 15 retrieved chunks fit well within 400K tokens (typical prompt is ~8K tokens), and the cost per query is negligible (~$0.006 per question at average prompt size).

### Backend selection logic

No code branching — the same `openai.OpenAI` client handles both:

```
OPENAI_API_KEY set      → base_url = https://api.openai.com/v1  (OpenAI)
OPENAI_API_KEY not set  → base_url = http://localhost:11434/v1   (Ollama)
```

`--model` flag overrides the model string. `--model ollama:llama3.2` strips the `ollama:` prefix and routes to the local base URL regardless of whether an API key is set.

---

## Prompt design

### System prompt

```
You are a financial analyst assistant. Answer questions using only the
provided source passages from SEC EDGAR filings (10-K and 10-Q reports).

Rules:
- Cite every factual claim with the passage number in square brackets, e.g. [1] or [2][4].
- Do not cite a passage unless it directly supports the claim.
- If the passages do not contain enough information to answer, say so explicitly.
- Do not speculate beyond what the sources state.
- Be concise and precise. Use financial terminology correctly.
```

### Context block

Each retrieved chunk is formatted as a numbered passage header followed by its text:

```
[1] AAPL · 10-K · 2023-10-27 · Item 1A — Risk Factors
The following risk factors may materially affect our business...

[2] TSLA · 10-K · 2023-01-26 · Item 1A — Risk Factors
We face intense competition in each of our markets from existing...

...

Question: What risks do Apple and Tesla face regarding AI competition?
```

The header line gives the LLM enough metadata to reason about filing recency and company identity without exposing the full chunk dict.

### Why this format

- Numbered passages make citation instructions unambiguous
- Metadata in the header lets the model reason about whether a 2021 filing is still relevant without being told to
- Flat numbered list works with all models including Ollama — no JSON mode dependency
- Short header lines do not inflate token count significantly

---

## Citation handling

### Approach: inline markers (Plan A)

The model is instructed to embed `[n]` markers inline as it writes. After the LLM call, `parse_citations()` extracts all referenced indices, maps each to the corresponding chunk, and attaches full metadata.

**Validation step** — strips phantom citations:
- Any `[n]` where `n` is outside `1..len(chunks)` is removed from the answer text
- Any `[n]` where the chunk text does not appear to support the surrounding sentence is flagged (optional, heuristic)

This produces a `Citation` object per referenced chunk:

```python
@dataclass
class Citation:
    index:        int        # [n] marker value
    ticker:       str        # e.g. "AAPL"
    filing_type:  str        # "10-K" or "10-Q"
    filing_date:  str        # ISO-8601
    section_id:   str        # "Item 1A"
    section_name: str        # "Risk Factors"
    passage_text: str        # the full chunk text
    source_file:  str        # edgar_corpus/AAPL_10-K_2023-10-27.txt
```

### Why not structured output / JSON mode (Plan B)

JSON mode (`response_format={"type": "json_object"}`) would give cleaner machine-readable citations but:

- Not reliably supported by Ollama models — breaks the dev/prod parity requirement
- Adds a Pydantic validation layer that fails loudly on malformed output from smaller models
- Quoted excerpts in structured output can drift from the actual chunk text, creating false precision

Inline markers work across all backends. OpenAI structured outputs can be added later as an optional enhancement without changing the core design.

---

## Data structures

### `AnswerConfig`

```python
@dataclass
class AnswerConfig:
    model:            str   = "gpt-5.4-mini"   # or "ollama:llama3.2" etc.
    temperature:      float = 0.2              # low = more factual
    max_tokens:       int   = 1024
    top_k:            int   = 15               # chunks passed to retriever
    max_chunk_chars:  int   = 2000             # truncate chunks for small-context models
    provider:         str | None = None        # "openai" | "anthropic" | "local" | None
    api_key:          str | None = None        # user-supplied API key (not cached)
    base_url:         str | None = None        # override base URL for local/custom endpoints
    allowed_tickers:  list[str] | None = None  # corpus restriction; None = unrestricted
    retriever_config: RetrieverConfig = field(default_factory=RetrieverConfig)
```

`allowed_tickers` is set from the JWT claim at request time and passed into `RetrieverConfig` so the retriever restricts results to the user's allowed corpus. `provider`, `api_key`, and `base_url` support custom LLM endpoints configured via the Settings page.

`max_chunk_chars` guards against context overflow on `gpt-5.4-mini` (400K) and Ollama models with tighter limits. At 15 chunks × 2000 chars the context block is ~7,500 tokens — well within all supported models.

### `Answer`

```python
@dataclass
class Answer:
    question:      str
    answer_text:   str           # LLM output with [n] markers intact
    citations:     list[Citation]
    model_used:    str
    n_chunks_used: int
    retrieval_trace: RetrievalTrace | None   # set when --trace is passed
```

`answer_text` keeps the `[n]` markers so the frontend can replace them with interactive chips. `citations` is indexed so `citations[i]` corresponds to marker `[i+1]`.

---

## `answer.py` module structure

```
AnswerConfig          dataclass — all tuneable parameters
Citation              dataclass — one cited source passage
Answer                dataclass — complete response with citations
LLMClient             wraps openai.OpenAI / anthropic.Anthropic; routes by provider
  .complete(system, user, ...)          → str
  .stream(system, user, ...)            → Iterator[str]   (SSE token stream)
  .stream_messages(messages, ...)       → Iterator[str]   (multi-turn SSE stream)
build_chunk_context() formats retrieved chunks into numbered context block
build_prompt()        wraps build_chunk_context() with question for single-turn
parse_citations()     extracts [n] markers, maps to chunk list, validates
AnswerEngine          orchestrates the full pipeline
  .answer(question)                          → Answer
  .answer_with_trace(question)               → Answer  (with RetrievalTrace attached)
  .answer_stream(question)                   → Iterator[dict]   (SSE events)
  .followup_stream(history, question,
                   tokens_so_far, context_limit) → Iterator[dict]  (SSE events, multi-turn)
main()                CLI entry point
```

### Streaming event types

`answer_stream()` yields dicts in this order:

```
{"type": "sources",   "sources": [...]}
{"type": "chunk",     "text": "..."}    ← one per token
{"type": "citations", "valid": [1, 3]}
{"type": "done"}
{"type": "error",     "detail": "..."}  ← terminates stream on failure
```

`followup_stream()` yields the same events plus `token_count` events:

```
{"type": "token_count", "tokens_used": 4210, "context_limit": 128000}
```

emitted before the first `chunk` event (initial context size) and again after `done` (final accumulated size).

### `LLMClient` routing

The client now supports three provider backends:

```
provider="openai"    → api.openai.com/v1      (or custom base_url)
provider="anthropic" → anthropic Python SDK
provider="local"     → localhost:11434/v1      (Ollama-compatible)
None (auto)          → openai if OPENAI_API_KEY set, else local
```

Custom `api_key` and `base_url` allow user-supplied endpoints from the Settings page. Engines using user-supplied keys are never cached in the `_engines` dict in `api/main.py`.

### `LLMClient` routing

```
model string          base_url                          api_key
─────────────────     ────────────────────────────────  ──────────────────────
gpt-5.4-mini          https://api.openai.com/v1         OPENAI_API_KEY env var
gpt-5.4               https://api.openai.com/v1         OPENAI_API_KEY env var
gpt-5.5               https://api.openai.com/v1         OPENAI_API_KEY env var
ollama:<model>        http://localhost:11434/v1          "ollama" (placeholder)
```

If `OPENAI_API_KEY` is not set and the model is not prefixed with `ollama:`, the client warns and falls back to `ollama:llama3.2`.

---

## CLI interface

The script is at `src/answer/answer.py`. Run as a module:

```bash
# Dev — Ollama default
python -m src.answer.answer "What are NVDA's primary risk factors?"

# Dev — explicit model
python -m src.answer.answer "What are NVDA's risks?" --model ollama:llama3.1:8b

# Prod default (gpt-5.4-mini, requires OPENAI_API_KEY)
python -m src.answer.answer "What are NVDA's risks?"

# Prod high quality
python -m src.answer.answer "What are NVDA's risks?" --model gpt-5.4

# Show retrieval details
python -m src.answer.answer "Compare Apple and Tesla revenue growth" --trace

# Tune retrieval
python -m src.answer.answer "MSFT cloud revenue 2023" --top-k 20
```

### Example output

```
Question: What are NVDA's primary risk factors?

NVIDIA faces several significant risks. Supply chain concentration is a
key concern — the company relies on TSMC for substantially all of its
semiconductor fabrication [1]. Demand volatility in the gaming and data
centre segments has historically caused sharp revenue swings [2][5].
Increasing regulatory scrutiny around AI chip exports, particularly to
China, creates material revenue uncertainty [3].

Sources:
  [1] NVDA · 10-K · 2024-02-21 · Item 1A — Risk Factors
  [2] NVDA · 10-K · 2024-02-21 · Item 1A — Risk Factors
  [3] NVDA · 10-K · 2024-02-21 · Item 1A — Risk Factors
  [5] NVDA · 10-Q · 2023-08-23 · Item 1A — Risk Factors
```

---

## Cost per query (production)

Typical prompt: ~8,000 tokens (15 chunks × ~500 tokens avg + system prompt + question).  
Typical completion: ~400 tokens.

| Model | Input cost | Output cost | **Total / query** |
|---|---|---|---|
| `gpt-5.4-mini` | $0.006 | $0.0018 | **~$0.008** |
| `gpt-5.4` | $0.020 | $0.006 | **~$0.026** |
| `gpt-5.5` | $0.040 | $0.012 | **~$0.052** |
| Ollama (any) | $0 | $0 | **$0** |

At 1,000 questions: `gpt-5.4-mini` ≈ $8, `gpt-5.4` ≈ $26.

---

## Error handling

| Condition | Behaviour |
|---|---|
| `OPENAI_API_KEY` not set, non-Ollama model | Warning + fallback to `ollama:llama3.2` |
| Ollama not running | Clear error: `Ollama not reachable at localhost:11434 — run: ollama serve` |
| No chunks retrieved | Returns answer with a no-information message; citations list is empty |
| LLM returns no `[n]` markers | Answer returned as-is; citations list is empty; warning logged |
| Phantom `[n]` reference (n out of range) | Marker stripped from answer text silently |
| Rate limit / API error | Propagate with original error message; no silent retry |

---

## Future extensions

- **Structured output mode** — optional `--citation-mode structured` for OpenAI backends only; falls back to inline for Ollama
- **Answer caching** — hash(question + top-k chunk IDs) as cache key; useful for demo/eval runs
