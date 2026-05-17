# Testing Setup Guide

## Overview of what runs where

After the codebase restructure (see `docs/restructure_plan.md`), all pipeline scripts moved into `src/`. Run them as Python modules:

| Script | Module invocation | What it uses | Needs Ollama? | Needs API key? |
|---|---|---|---|---|
| `src/pipeline/chunk.py` | `python -m src.pipeline.chunk` | Pure Python | No | No |
| `src/pipeline/embed.py --model local` | `python -m src.pipeline.embed --model local` | sentence-transformers (CPU) | No | No |
| `src/pipeline/embed.py --model openai` | `python -m src.pipeline.embed --model openai` | OpenAI Embeddings API + ChromaDB | No | Yes (`OPENAI_API_KEY`) |
| `src/retrieval/retrieve.py` | `python -m src.retrieval.retrieve` | ChromaDB + sentence-transformers | No | No (local index) |
| `src/answer/answer.py --model ollama:*` | `python -m src.answer.answer --model ollama:llama3.2` | Ollama (local LLM) | Yes | No |
| `src/answer/answer.py --model gpt-5.4*` | `python -m src.answer.answer` | OpenAI Chat API | No | Yes (`OPENAI_API_KEY`) |

**Ollama is only needed for `answer.py`.** The embedding step runs entirely on CPU via `sentence-transformers`. The vector index is now ChromaDB (not FAISS) — see `docs/chromadb_migration.md`.

---

## Step 1 — Install Python dependencies

```bash
pip3 install -r requirements.txt
```

Installs: `openai`, `faiss-cpu`, `sentence-transformers`, `numpy`, `anthropic`.

Verify:

```bash
python3 -c "import faiss, sentence_transformers, numpy; print('dependencies OK')"
```

---

## Step 2 — Run the chunker

If `chunks.jsonl` does not exist yet:

```bash
python -m src.pipeline.chunk
```

Expected output: `50,676 chunks` written to `chunks.jsonl`. Takes ~30 seconds.

---

## Step 3 — Build the embedding index

### Option A — Local model (recommended for testing, free, no API key)

```bash
python -m src.pipeline.embed --model local
```

- Model: `all-MiniLM-L6-v2` (downloaded automatically on first run, ~90 MB)
- Vector store: ChromaDB (persisted to `chroma_db/`)
- Time: ~4 minutes on CPU (M-series Mac), ~8 minutes on Intel

### Option B — OpenAI (higher quality, costs ~$0.40)

```bash
export OPENAI_API_KEY=sk-...
python -m src.pipeline.embed --model openai
```

- Model: `text-embedding-3-small`
- Vector store: ChromaDB (persisted to `chroma_db/`)
- Time: ~4 minutes (rate-limit paced)

---

## Step 4 — Smoke-test the retriever

```bash
python -m src.retrieval.retrieve "What are Apple's biggest risk factors?" --trace
```

Expected output shows routing details and 15 ranked chunks. Verify:
- `Tickers: ['AAPL']`
- `Sections: ['Item 1A']`
- Results show `AAPL` chunks from `Item 1A — Risk Factors`

```bash
python -m src.retrieval.retrieve "Compare Apple and Microsoft revenue growth" --trace
```

Verify: `Tickers: ['AAPL', 'MSFT']`, results contain chunks from both companies.

---

## Step 5 — Set up Ollama (for answer.py)

Ollama is needed only when running `answer.py` locally. Two options: native Mac install or Docker.

### Option A — Native Mac install (simpler, recommended)

```bash
# Install via Homebrew
brew install ollama

# Start the Ollama server (runs in background)
ollama serve
```

Verify the server is running:

```bash
curl http://localhost:11434/api/tags
# Should return {"models":[...]}
```

Pull a model for development:

```bash
# Fast iteration (2 GB)
ollama pull llama3.2

# Better reasoning (4.7 GB) — use for quality testing
ollama pull llama3.1:8b
```

### Option B — Docker container

Requires Docker Desktop for Mac.

**CPU only:**

```bash
docker run -d \
  --name ollama \
  -p 11434:11434 \
  -v ollama_data:/root/.ollama \
  ollama/ollama
```

**With Apple Silicon GPU (Metal) — significantly faster:**

```bash
docker run -d \
  --name ollama \
  -p 11434:11434 \
  -v ollama_data:/root/.ollama \
  --device /dev/dri \
  ollama/ollama
```

> **Note:** GPU passthrough from Docker to Apple Silicon Metal is limited. Native install (`brew install ollama`) uses Metal acceleration automatically and is meaningfully faster on M-series Macs. Use Docker only if you need container isolation.

Pull a model into the container:

```bash
docker exec ollama ollama pull llama3.2
```

Verify:

```bash
curl http://localhost:11434/api/tags
```

To stop and restart:

```bash
docker stop ollama
docker start ollama
```

---

## Step 6 — Smoke-test answer.py

### With Ollama (no API key needed)

```bash
# Ensure ollama serve is running, then:
python -m src.answer.answer "What are NVDA's primary risk factors?" --model ollama:llama3.2 --trace
```

### With OpenAI

```bash
export OPENAI_API_KEY=sk-...
python -m src.answer.answer "What are NVDA's primary risk factors?" --trace
# Uses gpt-5.4-mini by default
```

Expected output structure:

```
── Retrieval ─────────────────────────────────────────────
  Tickers    : ['NVDA']
  Sections   : ['Item 1A']
  ...
  Chunks used: 15

── Answer  [llama3.2] ────────────────────────────────────
NVIDIA faces several significant risks. Supply chain concentration
is a key concern ... [1]. Increasing export controls on AI chips
to China create material revenue uncertainty [3].

── Sources ───────────────────────────────────────────────
  [1] NVDA · 10-K · 2024-02-21 · Item 1A
       edgar_corpus/NVDA_10K_2024-02-21_full.txt
  [3] NVDA · 10-K · 2024-02-21 · Item 1A
       edgar_corpus/NVDA_10K_2024-02-21_full.txt
```

---

## Troubleshooting

**`faiss-cpu` import error on Apple Silicon**

```bash
pip3 install faiss-cpu --no-binary :all:
```

**`sentence-transformers` downloads a model every run**

It caches to `~/.cache/huggingface/hub/` after the first download. If the first run is slow, that is expected.

**Ollama connection refused**

```bash
# Native: make sure the server is running
ollama serve

# Docker: check the container is up
docker ps | grep ollama
docker start ollama   # if stopped
```

**Ollama responds slowly on Intel Mac**

Llama 3.2 (3B) is the fastest option. For Intel without GPU, expect ~10–20 tokens/second. Switch to OpenAI if latency is blocking development.

**`OPENAI_API_KEY` not set warning when using Ollama**

Expected — the warning fires when no key is present and the model is not prefixed with `ollama:`. Use the prefix explicitly:

```bash
python -m src.answer.answer "..." --model ollama:llama3.2
```

**ChromaDB collection empty or missing**

Re-run `embed.py` after any change to `chunks.jsonl`:

```bash
python -m src.pipeline.embed --model local
```
