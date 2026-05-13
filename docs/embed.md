# embed.py — Index Builder

Reads `chunks.jsonl`, embeds every chunk's text field, and writes a FAISS vector index to `index.faiss`. Run once after `chunk.py`. The index is then loaded by `retrieve.py` at query time.

---

## Usage

```bash
# OpenAI text-embedding-3-small (default, needs OPENAI_API_KEY)
python embed.py

# Local all-MiniLM-L6-v2, no API key required
python embed.py --model local

# Override batch size (default 200)
python embed.py --batch-size 100

# Custom input / output paths
python embed.py --chunks data/chunks.jsonl --output data/index.faiss
```

---

## Arguments

| Argument | Default | Description |
|---|---|---|
| `--model` | `openai` | Embedding backend: `openai` or `local` |
| `--batch-size` | `200` | Chunks per API / inference call |
| `--chunks` | `chunks.jsonl` | Path to the chunked corpus |
| `--output` | `index.faiss` | Path to write the FAISS index |

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

`index.faiss` — a `faiss.IndexFlatIP` (inner product index) containing one normalised float32 vector per chunk. The vector at position `i` in the index corresponds to the chunk at line `i` in `chunks.jsonl`.

### Index type

`IndexFlatIP` performs exact nearest-neighbour search using inner product similarity. After L2 normalisation (applied during embedding), inner product is equivalent to cosine similarity. Exact search is used rather than an approximate index (HNSW, IVF) because:

- At 50,676 vectors, exact search takes ~2ms per query — fast enough for a live demo
- No training step required
- No recall trade-off

Rebuild with an approximate index if the corpus grows beyond ~500k chunks and query latency becomes a concern.

---

## Pipeline internals

### 1. Load chunks

All records from `chunks.jsonl` are loaded into a list. The `text` field of each record is extracted as the string to embed.

### 2. Embed in batches

Chunks are sent in batches of `--batch-size` to the chosen embedding function. Progress is printed per batch with elapsed time.

For the OpenAI backend, a 50ms sleep is inserted between batches to stay within rate limits on Tier 1 accounts (3,000 RPM / 1M TPM).

### 3. L2 normalise

Each embedding vector is L2-normalised before being added to the FAISS index:

```python
norms = np.linalg.norm(vecs, axis=1, keepdims=True)
vecs  = vecs / np.where(norms == 0, 1.0, norms)
```

This ensures that inner product scores in the index equal cosine similarity scores, which are more interpretable (range roughly −1 to 1). The query vector is normalised the same way in `retrieve.py`.

### 4. Write index

The FAISS index is written to disk with `faiss.write_index()`. The index file stores both the vectors and the dimension metadata. No separate metadata file is needed because chunk metadata is loaded from `chunks.jsonl` at retrieval time (the index position maps 1:1 to line number in `chunks.jsonl`).

---

## Rebuilding

Rebuild the index whenever `chunks.jsonl` changes (i.e. after re-running `chunk.py`). The index position → chunk line mapping must stay in sync.

```bash
python chunk.py      # regenerate chunks.jsonl
python embed.py      # rebuild index.faiss
```

To switch embedding models, delete the old `index.faiss` and rebuild:

```bash
rm index.faiss
python embed.py --model local   # or openai
```

---

## Disk and memory

| Model | Index size | RAM at query time |
|---|---|---|
| `openai` (dim=1536) | ~300 MB | ~300 MB (loaded fully by FAISS) |
| `local` (dim=384) | ~78 MB | ~78 MB |

`retrieve.py` loads the index into memory on first query. On a machine with 8 GB RAM either model is comfortably within budget.
