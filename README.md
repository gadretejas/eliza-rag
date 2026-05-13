# SEC EDGAR RAG System

A retrieval-augmented generation system for answering business questions over SEC 10-K and 10-Q filings. Given a natural-language question, it retrieves the most relevant passages from a corpus of 246 filings across 54 major US companies and produces a grounded, cited answer in a single LLM call.

Example questions:
- "What are the primary risk factors facing Apple, Tesla, and JPMorgan?"
- "How has NVIDIA's revenue and growth outlook changed over the last two years?"
- "What regulatory risks do the major pharmaceutical companies face?"

---

## Project structure

```
.
├── chunk.py              # Stage 1 — structural chunker: corpus → chunks.jsonl
├── embed.py              # Stage 2 — index builder: chunks.jsonl → index.faiss
├── retrieve.py           # Stage 3 — hybrid retriever: question → ranked chunks
├── answer.py             # Stage 4 — answer generator: question → cited answer
├── requirements.txt
├── prompts/
│   └── system_prompt.md  # LLM system prompt (loaded at runtime by answer.py)
├── edgar_corpus/         # 246 SEC filings (.txt) + manifest.json
└── docs/
    ├── chunking_strategy.md       # Chunking design rationale
    ├── chunking_implementation.md # chunk.py full technical reference
    ├── embed.md                   # embed.py reference
    ├── retrieve.md                # retrieve.py reference
    ├── retrieval_design.md        # Retrieval system design doc
    ├── answer_generation.md       # Answer generation design doc
    ├── system_prompt.md           # System prompt design and iteration log
    ├── embedding_models.md        # Embedding model cost analysis and decision
    └── testing_setup.md           # Step-by-step environment setup guide
```

Generated files (gitignored — rebuild from scripts):

```
chunks.jsonl    # 50,676 chunks with metadata
index.faiss     # FAISS vector index (78 MB local / 311 MB OpenAI)
```

---

## Quick start

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Chunk the corpus

```bash
python3 chunk.py
# → chunks.jsonl  (50,676 chunks, ~30s)
```

### 3. Build the vector index

```bash
# Free — local all-MiniLM-L6-v2 model, no API key needed (~4 min on CPU)
python3 embed.py --model local

# Higher quality — OpenAI text-embedding-3-small (~$0.40, ~4 min)
export OPENAI_API_KEY=sk-...
python3 embed.py
```

### 4. Ask a question

```bash
# Dev — Ollama (free, requires ollama serve + ollama pull llama3.2)
python3 answer.py "What are NVDA's primary risk factors?" --model ollama:llama3.2

# Prod — OpenAI (requires OPENAI_API_KEY)
python3 answer.py "What are NVDA's primary risk factors?"
```

---

## Pipeline

### Stage 1 — Chunking (`chunk.py`)

Reads every `*_full.txt` file in `edgar_corpus/` and splits it into structured chunks by SEC Item header. Handles three PDF-to-text format variants across the corpus (AAPL, BLK, AMZN styles). Produces `chunks.jsonl` where each line is:

```json
{
  "ticker": "AAPL",
  "company": "Apple Inc",
  "filing_type": "10-K (Annual Report)",
  "filing_date": "2024-11-01",
  "report_period": "2024-09-28",
  "quarter": "2024Q3",
  "cik": "0000320193",
  "section_id": "Item 1A",
  "section_name": "Risk Factors",
  "content_type": "text",
  "chunk_index": 3,
  "source_file": "AAPL_10K_2024Q3_2024-11-01_full.txt",
  "text": "The Company's business faces risks including..."
}
```

**Output:** 50,676 chunks · median 1,859 chars · 248 table chunks  
**Docs:** [docs/chunking_strategy.md](docs/chunking_strategy.md) · [docs/chunking_implementation.md](docs/chunking_implementation.md)

---

### Stage 2 — Embedding (`embed.py`)

Embeds every chunk's `text` field and writes a FAISS `IndexFlatIP` to `index.faiss`. L2-normalised vectors make inner product equivalent to cosine similarity.

```bash
python3 embed.py [--model openai|local] [--batch-size 200]
```

| Backend | Model | Dim | Index size | Cost |
|---|---|---|---|---|
| `openai` (default) | text-embedding-3-small | 1536 | 311 MB | ~$0.40 |
| `local` | all-MiniLM-L6-v2 | 384 | 78 MB | free |

The embedding model used at index time is auto-detected at query time from the index dimension.  
**Docs:** [docs/embed.md](docs/embed.md) · [docs/embedding_models.md](docs/embedding_models.md)

---

### Stage 3 — Retrieval (`retrieve.py`)

Single-shot hybrid retrieval pipeline:

```
question → QueryRouter → metadata-filtered ANN search → cross-encoder re-rank
         → per-company balancing → top-k chunks
```

- **QueryRouter** — keyword-based extraction of tickers (54 companies), section filters (Item 1A/7/8), date range, and filing type. No LLM call.
- **VectorIndex** — FAISS ANN search with 3-level metadata post-filter fallback (full → relax date → relax section).
- **Reranker** — `cross-encoder/ms-marco-MiniLM-L-6-v2` (local) or Cohere Rerank v3 (API).
- **Balancing** — guarantees minimum representation per company for multi-ticker questions.

```bash
python3 retrieve.py "What are Apple's biggest risk factors?" --trace
python3 retrieve.py "Compare MSFT and GOOG cloud revenue" --top-k 20
```

**Docs:** [docs/retrieve.md](docs/retrieve.md) · [docs/retrieval_design.md](docs/retrieval_design.md)

---

### Stage 4 — Answer generation (`answer.py`)

Formats retrieved chunks as a numbered context block, calls an LLM, and parses inline `[n]` citations back to source chunk metadata.

```bash
python3 answer.py "question" [--model MODEL] [--top-k N] [--trace]
```

**LLM backends** — plug-and-play via a single flag:

| `--model` value | Routes to | Requires |
|---|---|---|
| `gpt-5.4-mini` (default) | OpenAI API | `OPENAI_API_KEY` |
| `gpt-5.4` | OpenAI API | `OPENAI_API_KEY` |
| `ollama:llama3.2` | Ollama local | `ollama serve` |
| `ollama:llama3.1:8b` | Ollama local | `ollama serve` |

All backends use the OpenAI-compatible API — no branching logic, no extra dependencies.

The system prompt is loaded from `prompts/system_prompt.md` at runtime. Edit the prompt without touching Python.

**Example output:**
```
── Answer  [gpt-5.4-mini] ────────────────────────────────────────────────
NVIDIA faces several significant risks. Supply chain concentration is a
key concern — the company relies on TSMC for substantially all of its
semiconductor fabrication [1]. Increasing export controls on AI chips
to China create material revenue uncertainty [3].

── Sources ───────────────────────────────────────────────────────────────
  [1] NVDA · 10-K · 2024-02-21 · Item 1A
       edgar_corpus/NVDA_10K_2024Q1_2024-02-21_full.txt
  [3] NVDA · 10-K · 2024-02-21 · Item 1A
       edgar_corpus/NVDA_10K_2024Q1_2024-02-21_full.txt
```

**Docs:** [docs/answer_generation.md](docs/answer_generation.md) · [docs/system_prompt.md](docs/system_prompt.md)

---

## Corpus

| Attribute | Value |
|---|---|
| Total filings | 246 |
| Annual reports (10-K) | 89 |
| Quarterly reports (10-Q) | 157 |
| Companies | 54 |
| Date range | 2022–2026 |
| Total tokens | ~20M |

Sectors: Technology · Financial Services · Healthcare · Consumer · Energy · Industrial

Companies with multi-year quarterly coverage: AAPL, AMZN, DIS, GOOG, JNJ, KO, MSFT, NVDA, PFE, TSLA, UNH, XOM and others.

---

## Environment variables

| Variable | Required for |
|---|---|
| `OPENAI_API_KEY` | `embed.py --model openai`, `answer.py` with OpenAI models |
| `COHERE_API_KEY` | `retrieve.py --reranker cohere` (optional) |

---

## Full setup guide

See [docs/testing_setup.md](docs/testing_setup.md) for step-by-step instructions including dependency install, Ollama setup (native Mac and Docker), and smoke-test commands for every stage.
