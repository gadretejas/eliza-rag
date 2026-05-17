# ChromaDB Migration Plan

## Status: Implemented

The migration is complete. `src/pipeline/embed.py` writes to ChromaDB, `src/retrieval/retrieve.py` uses a ChromaDB-backed `VectorIndex`, and `index.faiss` / `chunks_path` have been removed from `RetrieverConfig`. The actual implementation uses `chromadb.PersistentClient(path=CHROMA_PATH)` (the embedded client) rather than the HTTP Docker service described in Phase 1 — this is a simpler deployment that avoids the Docker dependency while keeping the same ChromaDB API. The `docker-compose.yml` was not created. Date filtering is applied in Python post-retrieval rather than via ChromaDB `$gte/$lte` operators because ChromaDB's `where` clause only supports numeric comparisons, and filing dates are stored as ISO-8601 strings.

---

## Why migrate

The current FAISS implementation stores vectors in `index.faiss` and metadata/text in `chunks.jsonl` as two separate files that must stay in sync manually. This is the fundamental limitation:

- A full index rebuild is required whenever the corpus changes
- Metadata filtering is a Python post-filter loop, not a database operation
- There is no way to add, update, or delete individual documents
- The architecture cannot be presented as a production vector store

ChromaDB replaces both files with a single persistent service. Vectors, metadata, and document text are stored together in a collection. Metadata filtering happens at query time inside the database. New filings can be indexed incrementally without touching existing data.

**Scalability story after migration:** the vector store is a Docker service decoupled from the application. Swapping ChromaDB for a hosted provider (Pinecone, Weaviate, Qdrant) is a single config change — the query interface is identical.

---

## What changes, what stays the same

### Changes
| File | Change |
|---|---|
| `embed.py` | Write to ChromaDB collection instead of `index.faiss` |
| `retrieve.py` | Replace `VectorIndex` class with ChromaDB client wrapper |
| `requirements.txt` | Add `chromadb>=0.6` |
| `docker-compose.yml` | New — runs ChromaDB as a persistent HTTP service |
| `.gitignore` | Add `chroma_store/` (local persistent data directory) |
| `docs/embed.md` | Update for ChromaDB output |
| `docs/retrieve.md` | Update `VectorIndex` section |
| `docs/testing_setup.md` | Update setup steps |
| `README.md` | Update architecture diagram and quick start |

### Unchanged
| File | Reason |
|---|---|
| `chunk.py` | Chunking logic is independent of the store |
| `chunks.jsonl` | Still used as input to `embed.py`; source of truth for the corpus |
| `answer.py` | Depends only on `HybridRetriever.retrieve()` — interface unchanged |
| `prompts/system_prompt.md` | Unaffected |
| `QueryRouter` | Pure text processing, no store dependency |
| `Reranker` | Operates on retrieved chunk dicts, not the store |
| `_balance()` | Operates on ranked results, not the store |
| `RetrieverConfig` | Fields remain the same; `index_path` replaced by `chroma_host/port` |

---

## ChromaDB concepts used in this migration

| Concept | Role in this project |
|---|---|
| **Collection** | Named index — equivalent to `index.faiss`. One collection: `sec_filings` |
| **Document** | The chunk `text` field stored alongside the vector |
| **Metadata** | All chunk fields except `text` stored as filterable key-value pairs |
| **ID** | Unique chunk identifier: `{source_file}_{chunk_index}` |
| **Embedding** | float32 vector — computed by `embed.py`, stored in the collection |
| **`where` filter** | Dict of metadata conditions applied at query time — replaces `VectorIndex._matches()` |
| **HTTP client** | `chromadb.HttpClient(host, port)` — connects to the Docker service |
| **Embedded client** | `chromadb.PersistentClient(path)` — single-process, no Docker, for local dev |

---

## Phase 1 — Infrastructure

**Goal:** ChromaDB running as a persistent Docker service, reachable from Python.

### 1.1 — Create `docker-compose.yml`

```yaml
services:
  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8000:8000"
    volumes:
      - chroma_store:/chroma/chroma
    environment:
      - ANONYMIZED_TELEMETRY=false
      - ALLOW_RESET=true

volumes:
  chroma_store:
```

Key decisions:
- `ALLOW_RESET=true` enables `client.reset()` during development — delete before production
- Named Docker volume `chroma_store` persists data across container restarts
- Port 8000 is ChromaDB's default HTTP port

### 1.2 — Add `chromadb` to `requirements.txt`

```
chromadb>=0.6
```

### 1.3 — Verify connectivity

```bash
docker compose up -d
pip3 install chromadb

python3 -c "
import chromadb
client = chromadb.HttpClient(host='localhost', port=8000)
print(client.heartbeat())   # should print a timestamp
"
```

### 1.4 — Update `.gitignore`

Add `chroma_store/` for cases where `PersistentClient` is used locally without Docker.

**Deliverable:** ChromaDB container running, heartbeat confirmed, `requirements.txt` updated.

---

## Phase 2 — Rewrite `embed.py`

**Goal:** `embed.py` writes to the `sec_filings` ChromaDB collection instead of `index.faiss`.

### 2.1 — Collection design

Collection name: `sec_filings`

Each chunk is stored as:
- **id** — `"{source_file}__{chunk_index}"` e.g. `"AAPL_10K_2024Q3_2024-11-01_full.txt__3"` — globally unique, deterministic, human-readable
- **embedding** — float32 vector from the embedding model
- **document** — the `text` field (ChromaDB stores this for retrieval)
- **metadata** — all other chunk fields:

```python
{
    "ticker":       "AAPL",
    "company":      "Apple Inc",
    "filing_type":  "10-K (Annual Report)",
    "filing_date":  "2024-11-01",
    "report_period":"2024-09-28",
    "quarter":      "2024Q3",
    "cik":          "0000320193",
    "section_id":   "Item 1A",
    "section_name": "Risk Factors",
    "content_type": "text",
    "chunk_index":  3,
    "source_file":  "AAPL_10K_2024Q3_2024-11-01_full.txt"
}
```

> **Important:** ChromaDB metadata values must be `str`, `int`, `float`, or `bool`. No lists, no nested dicts. All fields in the chunk schema are already scalar — no conversion needed.

### 2.2 — Normalisation

ChromaDB does not apply L2 normalisation before storage. Normalisation must still be applied in `embed.py` before calling `collection.add()`, exactly as it was before `faiss.IndexFlatIP.add()`. The `_normalize()` function is unchanged.

### 2.3 — Embedding function decision

Two options:

**Option A — Pre-compute in `embed.py`, pass to ChromaDB**  
`embed.py` computes vectors using the existing `_embed_openai()` / `_embed_local()` functions and passes them as the `embeddings=` argument to `collection.add()`. ChromaDB stores them as-is.

**Option B — ChromaDB embedding function**  
ChromaDB has a built-in embedding function API. Pass a `chromadb.utils.embedding_functions` object at collection creation time and let ChromaDB call the model.

**Decision: Option A.** The existing batching, rate-limit pacing, and progress reporting in `embed.py` are valuable and would be lost with Option B. Option A also makes the embedding step portable — the collection can be re-embedded with any model by deleting and recreating it.

### 2.4 — Idempotency

`embed.py` should be safely re-runnable. Use `collection.upsert()` instead of `collection.add()`. Upsert uses the chunk ID as the key — re-running with the same corpus overwrites existing vectors rather than duplicating them. This also enables incremental indexing of new filings without touching existing chunks.

### 2.5 — CLI changes

Remove `--output` flag (no longer a file path). Add:

```
--host     ChromaDB host (default: localhost)
--port     ChromaDB port (default: 8000)
--reset    Delete and recreate the collection before embedding (full rebuild)
```

### 2.6 — Removing `index.faiss` dependency

After migration, `index.faiss` is no longer generated or used. Add `index.faiss` to `.gitignore`.

**Deliverable:** `embed.py --model local` populates the `sec_filings` collection with 50,676 chunks. Verify with:

```bash
python3 -c "
import chromadb
c = chromadb.HttpClient(host='localhost', port=8000)
col = c.get_collection('sec_filings')
print(col.count())   # should print 50676
"
```

---

## Phase 3 — Rewrite `VectorIndex` in `retrieve.py`

**Goal:** replace the FAISS-backed `VectorIndex` class with a ChromaDB-backed equivalent. Everything above `VectorIndex` — `QueryRouter`, `Reranker`, `_balance`, `HybridRetriever` — is unchanged.

### 3.1 — New `VectorIndex` interface

The public interface stays identical so `HybridRetriever` requires zero changes:

```python
class VectorIndex:
    def __init__(self, host: str, port: int, collection_name: str) -> None: ...
    def search(
        self,
        query_vec: np.ndarray,
        filters: dict,
        top_k: int,
        oversample_factor: int = 8,
    ) -> list[tuple[float, dict]]: ...
```

### 3.2 — Translating filters to ChromaDB `where` clauses

The existing `filters` dict maps to ChromaDB's `where` syntax:

| Current filter | ChromaDB `where` equivalent |
|---|---|
| `tickers: ["AAPL"]` | `{"ticker": {"$in": ["AAPL"]}}` |
| `tickers: ["AAPL", "MSFT"]` | `{"ticker": {"$in": ["AAPL", "MSFT"]}}` |
| `sections: ["Item 1A"]` | `{"section_id": {"$in": ["Item 1A"]}}` |
| `date_from: "2023-01-01"` | `{"filing_date": {"$gte": "2023-01-01"}}` |
| `filing_type: "10-K"` | `{"filing_type": {"$eq": "10-K (Annual Report)"}}` |
| `text_only: True` | `{"content_type": {"$eq": "text"}}` |

Multiple conditions are combined with `$and`:

```python
{"$and": [
    {"ticker": {"$in": ["AAPL"]}},
    {"section_id": {"$in": ["Item 1A"]}},
    {"filing_date": {"$gte": "2023-01-01"}},
]}
```

> **Note on `filing_type`:** the stored value is `"10-K (Annual Report)"`, not `"10-K"`. The filter translator must expand the short form to the full stored string, or use `{"$contains": "10-K"}` — ChromaDB does not support `$startswith`, so this needs a mapping dict.

### 3.3 — Oversample and fallback

ChromaDB's `.query()` takes `n_results` directly — no separate ANN search step. Pass `n_results = top_k * oversample_factor` and apply the `where` filter in the same call.

The three-level fallback (full → relax date → relax section+date) is replicated by building progressively looser `where` dicts and retrying, same logic as the current FAISS implementation.

### 3.4 — Result format

ChromaDB `.query()` returns:

```python
{
    "ids":        [["id1", "id2", ...]],
    "documents":  [["text1", "text2", ...]],
    "metadatas":  [[{...}, {...}, ...]],
    "distances":  [[0.12, 0.34, ...]],   # L2 distance or cosine distance
}
```

Reconstruct the `(score, chunk_dict)` tuple format expected by `Reranker` and `_balance`:

```python
chunk = {**metadata, "text": document}
score = 1.0 - distance   # convert cosine distance → similarity score
```

> ChromaDB returns cosine **distance** (0 = identical, 2 = opposite). Convert to similarity with `1 - distance` to preserve descending sort order expected by the rest of the pipeline.

### 3.5 — `RetrieverConfig` changes

Replace `index_path: Path` with:

```python
chroma_host:       str = "localhost"
chroma_port:       int = 8000
chroma_collection: str = "sec_filings"
```

Remove `chunks_path` — chunk text is now stored inside ChromaDB, not read from `chunks.jsonl` at query time. `chunks.jsonl` remains on disk as the authoritative corpus source but is only read by `embed.py`.

### 3.6 — Dimension auto-detection

The current `_load_embedder()` reads `idx.d` from the FAISS index to detect whether it was built with OpenAI (1536) or local (384) embeddings. With ChromaDB, store the model name in collection metadata at embed time:

```python
collection = client.get_or_create_collection(
    name="sec_filings",
    metadata={"embedding_model": "local"}   # or "openai"
)
```

`_load_embedder()` reads `collection.metadata["embedding_model"]` instead of the FAISS dimension.

**Deliverable:** `retrieve.py "What are Apple's risks?" --trace` returns 15 chunks from ChromaDB with correct metadata. The `Reranker` and citation chain in `answer.py` are unaffected.

---

## Phase 4 — Validation

**Goal:** confirm the migrated pipeline produces equivalent results to FAISS and all components integrate correctly end to end.

### 4.1 — Collection integrity check

```bash
python3 -c "
import chromadb
c = chromadb.HttpClient(host='localhost', port=8000)
col = c.get_collection('sec_filings')

print('Total chunks :', col.count())           # expect 50,676

# Spot-check a known chunk
result = col.get(ids=['AAPL_10K_2024Q3_2024-11-01_full.txt__3'])
print('Ticker       :', result['metadatas'][0]['ticker'])   # AAPL
print('Section      :', result['metadatas'][0]['section_id'])
print('Text preview :', result['documents'][0][:100])
"
```

### 4.2 — Retrieval smoke tests

Run the same questions against both FAISS (if still available) and ChromaDB and compare top-3 chunk IDs:

```bash
# Test 1 — single company, section filter
python -m src.retrieval.retrieve "What are Apple's biggest risk factors?" --trace

# Test 2 — multi-company comparison
python -m src.retrieval.retrieve "Compare Apple and Microsoft revenue growth" --trace

# Test 3 — temporal filter
python -m src.retrieval.retrieve "What risks did NVDA face in 2023?" --trace

# Test 4 — filing type filter
python -m src.retrieval.retrieve "Apple annual report business overview" --trace
```

For each test verify:
- Correct tickers in results
- Correct section_id in results
- Scores are non-zero and descending
- `n_candidates` is plausible (> 0, ≤ top_k × oversample_factor)

### 4.3 — End-to-end answer test

```bash
python -m src.answer.answer "What are NVDA's primary risk factors?" --model ollama:llama3.2 --trace
```

Verify:
- Answer text contains `[n]` citation markers
- Sources section lists NVDA chunks
- No errors in the pipeline

### 4.4 — Incremental index test

Verify that `upsert` works correctly — re-running `embed.py` on the same corpus should not duplicate chunks:

```bash
python -m src.pipeline.embed --model local
python -c "
import chromadb
from src.config import CHROMA_PATH, COLLECTION_NAME
c = chromadb.PersistentClient(path=CHROMA_PATH)
print(c.get_collection(COLLECTION_NAME).count())   # must still be 50,676
"
```

**Deliverable:** all smoke tests pass, chunk count correct after re-embed.

---

## Phase 5 — Documentation and cleanup

**Goal:** update all docs to reflect ChromaDB, remove FAISS references, communicate the scalability story clearly.

### 5.1 — Files to update

| File | Changes |
|---|---|
| `docs/embed.md` | Replace FAISS output section with ChromaDB collection section; update CLI args; add Docker prerequisite |
| `docs/retrieve.md` | Replace `VectorIndex` FAISS section with ChromaDB client section; update `RetrieverConfig` table; update filter translation table |
| `docs/testing_setup.md` | Replace Step 3 (index build) and Step 4 (retriever smoke test) with ChromaDB-aware versions; add `docker compose up` as a prerequisite |
| `README.md` | Update architecture, quick start, and project structure |

### 5.2 — New doc section: scalability story

Add a `docs/architecture.md` section titled "Scaling beyond this demo" that explicitly frames the design decisions for an interviewer audience:

- ChromaDB as a service mirrors production vector DB architecture (Pinecone, Weaviate, Qdrant)
- Incremental indexing (`upsert`) means new filings can be added without downtime
- The retrieval interface (`VectorIndex`) is an abstraction — swapping the backend is a config change, not a rewrite
- At 50k vectors ChromaDB is fast enough for live demos; at 50M vectors swap to a distributed store

### 5.3 — Cleanup

- Remove `index.faiss` from the repository if present
- Remove `--output` flag from `embed.py`
- Remove `chunks_path` and `index_path` from `RetrieverConfig`
- Remove the `ntotal == len(chunks)` validation (no longer needed — ChromaDB is the single source of truth)

**Deliverable:** all docs consistent, no FAISS references in user-facing documentation.

---

## Phase summary

| Phase | Scope | Files changed | Risk |
|---|---|---|---|
| 1 — Infrastructure | Docker, deps, connectivity | `docker-compose.yml`, `requirements.txt`, `.gitignore` | Low |
| 2 — embed.py | Write to ChromaDB | `embed.py` | Medium — new upsert logic, ID scheme |
| 3 — retrieve.py | Replace VectorIndex | `retrieve.py` | Medium — filter translation, distance→similarity conversion |
| 4 — Validation | End-to-end testing | None (test commands only) | Low |
| 5 — Docs & cleanup | Documentation, FAISS removal | Docs, README, `.gitignore` | Low |

Each phase is independently testable. Phase 3 can begin before Phase 2 is complete by pointing `VectorIndex` at a partially populated collection.

---

## Rollback plan

Keep `index.faiss` and the FAISS-backed `VectorIndex` until Phase 4 validation passes. The original `VectorIndex` can be restored in under 5 minutes by reverting `retrieve.py` and setting `index_path` back in `RetrieverConfig`. No data is lost — `chunks.jsonl` is unchanged throughout.
