# embed.py — ChromaDB Collection Builder

Located at `src/pipeline/embed.py`. Reads from `contextualized_chunks.db` (falling back to `chunks.jsonl` if the DB is absent), embeds every chunk's enriched text, and writes to a ChromaDB persistent collection. Run once after `contextualize.py` (or `chunk.py` if skipping contextualization). The ChromaDB collection is then queried by `src/retrieval/retrieve.py` at query time.

The script moved from the project root to `src/pipeline/` as part of the restructure (see `docs/restructure_plan.md`). Run it as a module: `python -m src.pipeline.embed`.

---

## Usage

```bash
# OpenAI text-embedding-3-small (default, needs OPENAI_API_KEY)
python -m src.pipeline.embed

# Local all-MiniLM-L6-v2, no API key required
python -m src.pipeline.embed --model local

# Delete existing collection and rebuild from scratch
python -m src.pipeline.embed --reset

# Parallel embedding workers (default: 5)
python -m src.pipeline.embed --workers 10

# Custom ChromaDB store location
python -m src.pipeline.embed --path ./chroma_store
```

---

## Arguments

| Argument | Default | Description |
|---|---|---|
| `--model` | `openai` | Embedding backend: `openai` or `local` |
| `--batch-size` | `200` | Chunks per embedding call |
| `--reset` | off | Delete and rebuild the ChromaDB collection from scratch |
| `--workers` | `5` | Parallel embedding workers |
| `--path` | `chroma_db/` (from `src/config.py`) | ChromaDB store directory |

---

## Embedding models

### `openai` (default)

**Model**: `text-embedding-3-small`  
**Dimension**: 1536  
**Requires**: `OPENAI_API_KEY` environment variable  
**Cost**: ~$0.02 / 1M tokens. Full corpus (~25M tokens) ≈ $0.50  
**Speed**: ~250 batches at 200 chunks each, ~4 minutes with rate-limit pacing

```bash
export OPENAI_API_KEY=sk-...
python embed.py
```

The OpenAI embeddings are higher quality for general financial text. Recommended if you already have an API key set up for the answer step.

### `local`

**Model**: `all-MiniLM-L6-v2` (via `sentence-transformers`)  
**Dimension**: 384  
**Requires**: nothing beyond `pip install sentence-transformers`  
**Cost**: free  
**Speed**: ~245 seconds on CPU for the full corpus

```bash
python embed.py --model local
```

The local model produces a smaller index (78 MB vs ~300 MB for OpenAI) and requires no API key. Quality is somewhat lower for nuanced financial language but sufficient for the demo question set.

> **Important**: the embedding model used for `embed.py` must match the model used to embed queries at retrieval time. `retrieve.py` auto-detects the index dimension and selects the correct query embedder: dimension 1536 → OpenAI, dimension 384 → local. Do not mix models without rebuilding the index.

---

## Output

A ChromaDB persistent collection stored in `chroma_db/` (path configured in `src/config.py` via `CHROMA_PATH`). Each document in the collection stores:

- The embedded text (enriched chunk from `contextualized_chunks.db`, or raw text from `chunks.jsonl` as fallback)
- All chunk metadata as ChromaDB metadata fields (ticker, filing_date, section_id, content_type, etc.)

ChromaDB uses approximate nearest-neighbour search (HNSW index) internally. At 50,676 vectors the index is fast (~2ms per query) and requires no training. See `docs/chromadb_migration.md` for the full migration details.

---

## Pipeline internals

### 1. Load chunks

All records from `chunks.jsonl` are loaded into a list. The `text` field of each record is extracted as the string to embed.

### 2. Embed in batches

Chunks are sent in batches of `--batch-size` to the chosen embedding function. Progress is printed per batch with elapsed time.

For the OpenAI backend, a 50ms sleep is inserted between batches to stay within rate limits on Tier 1 accounts (3,000 RPM / 1M TPM).

### 3. L2 normalise

Each embedding vector is L2-normalised before being stored in ChromaDB:

```python
norms = np.linalg.norm(vecs, axis=1, keepdims=True)
vecs  = vecs / np.where(norms == 0, 1.0, norms)
```

This ensures cosine similarity scores when ChromaDB performs ANN search. The query vector is normalised the same way in `src/retrieval/retrieve.py`.

### 4. Write to ChromaDB

Each batch of embedded chunks is upserted into the ChromaDB collection using the chunk ID as the document ID. Re-running embed without `--reset` will upsert (overwrite) existing chunks and add new ones, leaving unchanged chunks intact.

---

## Rebuilding

Rebuild the collection whenever `chunks.jsonl` or `contextualized_chunks.db` changes (i.e. after re-running `chunk.py` or `contextualize.py`).

```bash
python -m src.pipeline.chunk          # regenerate chunks.jsonl
python -m src.pipeline.contextualize  # regenerate contextualized_chunks.db
python -m src.pipeline.embed          # upsert into ChromaDB
```

To switch embedding models, reset the collection and rebuild:

```bash
python -m src.pipeline.embed --reset --model local   # or openai
```

---

## Disk and memory

| Model | ChromaDB store size | Notes |
|---|---|---|
| `openai` (dim=1536) | ~300–350 MB | Stored in `chroma_db/` directory |
| `local` (dim=384) | ~80–100 MB | Stored in `chroma_db/` directory |

ChromaDB keeps the HNSW index resident in memory when the client is open. `src/retrieval/retrieve.py` holds a persistent client open for the lifetime of the API process. On a machine with 8 GB RAM either model is comfortably within budget.
