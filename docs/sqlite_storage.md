# SQLite Storage — Design Document

## Why SQLite over JSON

`contextualized_chunks.json` at full corpus scale is ~311 MB of flat text. Every consumer of that file — embedding, inspection, debugging — must load the entire thing into memory to access a single record. This is the same architectural limitation that motivated the ChromaDB migration over FAISS.

SQLite replaces the flat JSON with a queryable, indexed, single-file database. It is part of the Python standard library (no new dependencies), supports concurrent reads, and allows incremental upserts — new filings can be added without rewriting the entire store.

### Scalability narrative

```
edgar_corpus/*.txt   →   chunks.jsonl       flat file, sequential scan only
chunks.jsonl         →   contextualized     SQLite, indexed, queryable
                         _chunks.db
contextualized       →   ChromaDB           vector database service,
_chunks.db                                  client-server, production-grade
```

Each step is a deliberate progression toward a production architecture. SQLite sits between the raw pipeline artifacts and the vector store — structured enough to query during development and inspection, simple enough to ship as a single file.

---

## Scope

### What changes
| File | Change |
|---|---|
| `contextualize.py` | Write to `contextualized_chunks.db` instead of `contextualized_chunks.json` |
| `.gitignore` | Replace `contextualized_chunks.json` with `contextualized_chunks.db` |
| `docs/cost_metrics.md` | Update storage format reference |
| `README.md` | Update pipeline output description |

### What stays the same
| File | Reason |
|---|---|
| `chunks.jsonl` | Still the raw chunking output and embed input |
| `contexts_cache.json` | Intermediate LLM output cache — stays as JSON (small, human-readable) |
| `embed.py` | Reads from `chunks.jsonl` today; will read from ChromaDB after migration |
| `contextualization_tester.py` | Test script — keep JSON output for easy inspection |

---

## Schema

### `chunks` table

Primary store for all enriched chunks.

```sql
CREATE TABLE IF NOT EXISTS chunks (
    id               TEXT    PRIMARY KEY,  -- "{source_file}__{chunk_index}"
    source_file      TEXT    NOT NULL,
    chunk_index      INTEGER NOT NULL,
    ticker           TEXT    NOT NULL,
    company          TEXT    NOT NULL,
    filing_type      TEXT    NOT NULL,
    filing_date      TEXT    NOT NULL,     -- ISO-8601 string, e.g. "2024-11-01"
    report_period    TEXT,
    quarter          TEXT,
    cik              TEXT,
    section_id       TEXT    NOT NULL,
    section_name     TEXT,
    content_type     TEXT    NOT NULL,     -- "text" or "table"
    document_context TEXT,
    section_context  TEXT,
    original_text    TEXT    NOT NULL,
    enriched_text    TEXT    NOT NULL
);
```

### `meta` table

Stores run metadata for auditability — when the DB was built, which model generated the contexts.

```sql
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Populated at write time:

| key | example value |
|---|---|
| `generated_at` | `2026-05-13T10:42:00Z` |
| `model` | `gpt-5.4-mini` |
| `total_chunks` | `50676` |
| `total_documents` | `246` |
| `avg_original_tokens` | `409` |
| `avg_enriched_tokens` | `701` |

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_ticker      ON chunks(ticker);
CREATE INDEX IF NOT EXISTS idx_section     ON chunks(section_id);
CREATE INDEX IF NOT EXISTS idx_filing_date ON chunks(filing_date);
CREATE INDEX IF NOT EXISTS idx_content     ON chunks(content_type);
CREATE INDEX IF NOT EXISTS idx_ticker_sec  ON chunks(ticker, section_id);
CREATE INDEX IF NOT EXISTS idx_ticker_date ON chunks(ticker, filing_date);
```

**Rationale per index:**
- `idx_ticker` — most queries filter by company
- `idx_section` — second most common filter (Item 1A, Item 7)
- `idx_filing_date` — temporal range queries ("filings since 2023")
- `idx_content` — filter table vs text chunks
- `idx_ticker_sec` — composite for the most common combined filter
- `idx_ticker_date` — composite for per-company timeline queries

---

## ID scheme

```python
id = f"{source_file}__{chunk_index}"
# e.g. "AAPL_10K_2024Q3_2024-11-01_full.txt__3"
```

- Globally unique across the entire corpus
- Deterministic — re-running produces the same IDs
- Human-readable — debuggable without a lookup table
- Double underscore (`__`) separator avoids collision with single underscores in filenames

---

## Write strategy: upsert

All writes use `INSERT OR REPLACE` (SQLite upsert). Re-running `contextualize.py` on an existing database overwrites changed rows and leaves unchanged rows intact. This means:

- New filings can be added incrementally without rebuilding from scratch
- Re-generated contexts (e.g. after prompt changes) update existing rows in place
- No duplicate rows regardless of how many times the script is run

---

## Estimated database size

From the tester: 417 chunks across 2 documents → 2.56 MB JSON.

| Format | Estimated size |
|---|---|
| `contextualized_chunks.json` | ~311 MB |
| `contextualized_chunks.db` (no indexes) | ~250 MB |
| `contextualized_chunks.db` (with indexes) | ~280 MB |

SQLite's binary storage and absence of JSON formatting overhead reduces size by ~10–15% over the equivalent JSON. The indexes add ~10–15% back.

---

## Example queries

These queries are executable immediately after `contextualize.py` completes, with no application code — using any SQLite client or the Python `sqlite3` module.

```sql
-- All chunks for AAPL Item 1A
SELECT chunk_index, filing_date, original_text
FROM chunks
WHERE ticker = 'AAPL' AND section_id = 'Item 1A'
ORDER BY filing_date DESC;

-- Most recent 10-K chunks for each company
SELECT ticker, filing_date, section_id, COUNT(*) as chunk_count
FROM chunks
WHERE filing_type LIKE '10-K%'
GROUP BY ticker, filing_date, section_id
ORDER BY ticker, filing_date DESC;

-- Chunks where document context was not generated (failed LLM call)
SELECT id, ticker, section_id
FROM chunks
WHERE document_context = '' OR document_context IS NULL;

-- Token inflation by section
SELECT section_id,
       AVG(LENGTH(original_text) / 4)  AS avg_original_tokens,
       AVG(LENGTH(enriched_text) / 4)  AS avg_enriched_tokens
FROM chunks
GROUP BY section_id
ORDER BY avg_enriched_tokens DESC;

-- All table chunks (content_type = 'table')
SELECT ticker, filing_date, section_id, original_text
FROM chunks
WHERE content_type = 'table'
LIMIT 20;
```

---

## Integration with the pipeline

### Current pipeline (after this change)

```
chunk.py        → chunks.jsonl
contextualize.py → contexts_cache.json + contextualized_chunks.db
embed.py        → reads chunks.jsonl → writes index.faiss (current)
                  reads contextualized_chunks.db → writes to ChromaDB (post-migration)
```

### embed.py integration (post-ChromaDB migration)

`embed.py` will read enriched chunks directly from `contextualized_chunks.db` instead of `chunks.jsonl`, using the `enriched_text` field as the embedding input and all metadata fields for ChromaDB storage:

```python
import sqlite3
conn = sqlite3.connect("contextualized_chunks.db")
conn.row_factory = sqlite3.Row
chunks = conn.execute("SELECT * FROM chunks ORDER BY source_file, chunk_index").fetchall()
```

This replaces the current `chunks.jsonl` line-by-line reader with a single SQL query that returns rows in a deterministic order.

---

## Tooling

The database can be inspected without writing any code:

- **DB Browser for SQLite** — free GUI, Mac/Windows/Linux: [sqlitebrowser.org](https://sqlitebrowser.org)
- **Python stdlib** — `import sqlite3` — no install required
- **CLI** — `sqlite3 contextualized_chunks.db` then `.tables`, `.schema`, `SELECT ...`

---

## What this does NOT solve

SQLite is a local, single-writer file database. It does not provide:

- Network access — cannot be queried from another machine without file sharing
- Horizontal scaling — single file, single process writes
- Vector similarity search — that remains ChromaDB's role

SQLite's role in this architecture is a structured, queryable intermediate store between the raw pipeline artifacts (`chunks.jsonl`, `contexts_cache.json`) and the production vector store (ChromaDB). It is not a replacement for ChromaDB.
