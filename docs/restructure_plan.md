# Codebase Restructure Plan

## Status: Implemented

The full restructure is complete. All files are in their target locations under `src/pipeline/`, `src/retrieval/`, `src/answer/`, `api/`, `tests/`, and `scripts/`. `src/config.py` is the single source of truth for all paths and constants. Note: `src/config.py` also exports `FOLLOWUP_SYSTEM_PROMPT_PATH` and `OPENAI_BASE_URL` which were added after this plan was written (for the follow-up chat and custom LLM support features respectively).

---

## Target Structure

```
eliza_assignment/
├── src/
│   ├── config.py                        # centralised path + constant config
│   ├── pipeline/                        # one-time data prep (run in order)
│   │   ├── __init__.py
│   │   ├── chunk.py
│   │   ├── contextualize.py
│   │   └── embed.py
│   ├── retrieval/                       # query-time retrieval logic
│   │   ├── __init__.py
│   │   └── retrieve.py
│   └── answer/                          # LLM answer generation
│       ├── __init__.py
│       └── answer.py
├── tests/                               # testers and validators
│   ├── contextualization_tester.py
│   ├── embedding_tester.py
│   └── validate_db.py
├── api/                                 # FastAPI backend (new)
│   ├── __init__.py
│   └── main.py
├── frontend/                            # React app (new)
│   └── ...
├── scripts/                             # dev/debug CLI tools
│   └── query_db.py
├── prompts/
│   └── system_prompt.md
├── docs/
│   └── ...
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Step 0 — Create `src/config.py` (do this first)

All hardcoded paths currently live as module-level constants scattered across
9 files. Before moving anything, introduce a single config module that every
file will import from. This eliminates the path-drift problem when files move.

```python
# src/config.py
from pathlib import Path

# Project root — always the directory containing src/
ROOT = Path(__file__).parent.parent

# Data artifacts
CORPUS_DIR        = ROOT / "edgar_corpus"
CHUNKS_PATH       = ROOT / "chunks.jsonl"
CACHE_PATH        = ROOT / "contexts_cache.json"
CONTEXTUALIZED_DB = ROOT / "contextualized_chunks.db"
CHROMA_PATH       = str(ROOT / "chroma_store")

# Test artifacts
TEST_DB_PATH      = ROOT / "contextualization_test_output.db"

# ChromaDB collection names
COLLECTION_NAME      = "sec_filings"
TEST_COLLECTION_NAME = "sec_filings_test"

# Embedding models
OPENAI_EMBED_MODEL = "text-embedding-3-small"
LOCAL_EMBED_MODEL  = "all-MiniLM-L6-v2"

# LLM
OLLAMA_BASE_URL    = "http://localhost:11434/v1"

# Prompts
PROMPTS_DIR        = ROOT / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.md"

# Logs
CONTEXTUALIZE_LOG  = ROOT / "contextualize.log"
EMBED_LOG          = ROOT / "embed.log"
```

---

## Step 1 — File moves

| Current location | New location | Notes |
|---|---|---|
| `chunk.py` | `src/pipeline/chunk.py` | |
| `contextualize.py` | `src/pipeline/contextualize.py` | |
| `embed.py` | `src/pipeline/embed.py` | |
| `retrieve.py` | `src/retrieval/retrieve.py` | |
| `answer.py` | `src/answer/answer.py` | |
| `contextualization_tester.py` | `tests/contextualization_tester.py` | |
| `embedding_tester.py` | `tests/embedding_tester.py` | |
| `validate_db.py` | `tests/validate_db.py` | |
| `query_db.py` | `scripts/query_db.py` | dev/debug tool, not a test |

---

## Step 2 — Import fixes per file

### `src/pipeline/chunk.py`

**Remove:**
```python
CORPUS_DIR  = Path("edgar_corpus")
OUTPUT_PATH = Path("chunks.jsonl")
```

**Add:**
```python
from src.config import CORPUS_DIR, CHUNKS_PATH as OUTPUT_PATH
```

---

### `src/pipeline/contextualize.py`

**Remove:**
```python
CHUNKS_PATH  = Path("chunks.jsonl")
CACHE_PATH   = Path("contexts_cache.json")
OUTPUT_PATH  = Path("contextualized_chunks.db")
LOG_PATH     = Path("contextualize.log")
OLLAMA_BASE_URL = "http://localhost:11434/v1"
```

**Add:**
```python
from src.config import (
    CHUNKS_PATH, CACHE_PATH, CONTEXTUALIZED_DB as OUTPUT_PATH,
    CONTEXTUALIZE_LOG as LOG_PATH, OLLAMA_BASE_URL,
)
```

---

### `src/pipeline/embed.py`

**Remove:**
```python
DB_PATH         = Path("contextualized_chunks.db")
CHUNKS_PATH     = Path("chunks.jsonl")
CHROMA_PATH     = "chroma_store"
COLLECTION_NAME = "sec_filings"
OPENAI_MODEL    = "text-embedding-3-small"
LOCAL_MODEL     = "all-MiniLM-L6-v2"
```

**Add:**
```python
from src.config import (
    CONTEXTUALIZED_DB as DB_PATH, CHUNKS_PATH, CHROMA_PATH,
    COLLECTION_NAME, OPENAI_EMBED_MODEL as OPENAI_MODEL,
    LOCAL_EMBED_MODEL as LOCAL_MODEL, EMBED_LOG,
)
```

---

### `src/retrieval/retrieve.py`

**Remove:**
```python
CHROMA_PATH     = "chroma_store"
COLLECTION_NAME = "sec_filings"
# hardcoded model names inside _make_openai_embedder() and _make_local_embedder()
```

**Add:**
```python
from src.config import (
    CHROMA_PATH, COLLECTION_NAME,
    OPENAI_EMBED_MODEL, LOCAL_EMBED_MODEL,
)
```

**Internal update** — replace hardcoded model name strings with config constants:
- `retrieve.py:744` `"text-embedding-3-small"` → `OPENAI_EMBED_MODEL`
- `retrieve.py:759` `"all-MiniLM-L6-v2"` → `LOCAL_EMBED_MODEL`

---

### `src/answer/answer.py`

**Remove:**
```python
PROMPTS_DIR        = Path(__file__).parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.md"
CORPUS_DIR         = Path("edgar_corpus")
OLLAMA_BASE_URL    = "http://localhost:11434/v1"
```

**Add:**
```python
from src.config import (
    SYSTEM_PROMPT_PATH, CORPUS_DIR, OLLAMA_BASE_URL,
)
```

**Cross-file import fix** — `answer.py` currently does:
```python
from retrieve import HybridRetriever, RetrieverConfig, RetrievalTrace
```
After the move this becomes:
```python
from src.retrieval.retrieve import HybridRetriever, RetrieverConfig, RetrievalTrace
```

---

### `tests/contextualization_tester.py`

**Remove:**
```python
CHUNKS_PATH     = Path("chunks.jsonl")
DEFAULT_OUT     = Path("contextualization_test_output.db")
OLLAMA_BASE_URL = "http://localhost:11434/v1"
```

**Add:**
```python
from src.config import (
    CHUNKS_PATH, TEST_DB_PATH as DEFAULT_OUT, OLLAMA_BASE_URL,
)
```

---

### `tests/embedding_tester.py`

**Remove:**
```python
DB_PATH         = Path("contextualized_chunks.db")
TEST_COLLECTION = "sec_filings_test"
CHROMA_PATH     = "chroma_store"
```

**Add:**
```python
from src.config import (
    CONTEXTUALIZED_DB as DB_PATH, TEST_COLLECTION_NAME as TEST_COLLECTION,
    CHROMA_PATH,
)
```

---

### `tests/validate_db.py`

**Remove:**
```python
DEFAULT_DB  = Path("contextualized_chunks.db")
FALLBACK_DB = Path("contextualization_test_output.db")
```

**Add:**
```python
from src.config import CONTEXTUALIZED_DB as DEFAULT_DB, TEST_DB_PATH as FALLBACK_DB
```

---

### `scripts/query_db.py`

**Remove:**
```python
DEFAULT_DB  = Path("contextualized_chunks.db")
FALLBACK_DB = Path("contextualization_test_output.db")
```

**Add:**
```python
from src.config import CONTEXTUALIZED_DB as DEFAULT_DB, TEST_DB_PATH as FALLBACK_DB
```

---

## Step 3 — `__init__.py` files

Create empty `__init__.py` in each new package so Python treats them as
importable modules:

```
src/__init__.py
src/pipeline/__init__.py
src/retrieval/__init__.py
src/answer/__init__.py
api/__init__.py
```

`tests/` and `scripts/` are not packages (no `__init__.py`) — they're run
directly as scripts.

---

## Step 4 — Running scripts after the move

All pipeline and test scripts are currently run from the project root as:
```bash
python3 chunk.py
python3 contextualize.py
```

After the move, two options:

**Option A — run as modules (recommended):**
```bash
python3 -m src.pipeline.chunk
python3 -m src.pipeline.contextualize
python3 -m src.pipeline.embed
python3 -m src.retrieval.retrieve "question"
python3 -m src.answer.answer "question"
python3 -m tests.embedding_tester
python3 -m scripts.query_db --summary
```

**Option B — thin CLI entry-point wrappers at root level:**
```python
# run_answer.py (root)
from src.answer.answer import main
if __name__ == "__main__":
    main()
```
This keeps the original `python3 answer.py` invocation working. Useful for
demos and the assignment submission.

The API will use Option A (module imports). For demos, Option B wrappers are
cleaner. **Recommend both**: entry-point wrappers at root + module imports in
the API.

---

## Step 5 — API skeleton (`api/main.py`)

Once files are moved, the FastAPI backend imports cleanly:

```python
from src.retrieval.retrieve import HybridRetriever, RetrieverConfig
from src.answer.answer import AnswerEngine, AnswerConfig

app = FastAPI()

@app.post("/api/ask")
async def ask(question: str):
    engine = AnswerEngine()
    result = engine.answer(question)
    return {"answer": result.text, "sources": result.citations}
```

Add to `requirements.txt`:
```
fastapi>=0.110
uvicorn>=0.29
```

---

## Step 6 — `.gitignore` updates

Add entries for new directories:
```
frontend/node_modules/
frontend/.next/
frontend/dist/
frontend/build/
```

---

## Step 7 — README updates

Update all command examples from `python3 chunk.py` style to
`python3 -m src.pipeline.chunk` style, or document the root-level
entry-point wrappers.

---

## Implementation order

1. Create `src/config.py`
2. Create all `__init__.py` files
3. Move files one folder at a time (pipeline → retrieval → answer → tests → scripts)
4. Update imports in each file immediately after moving it
5. Run smoke tests after each folder: `python3 -m src.pipeline.chunk --help`
6. Create root-level entry-point wrappers
7. Create `api/main.py` skeleton
8. Update `.gitignore` and `README.md`

---

## Risk notes

- **`prompts/` location** — `answer.py` currently uses `Path(__file__).parent / "prompts"`.
  After moving to `src/answer/answer.py`, `Path(__file__).parent` would resolve to
  `src/answer/` — wrong. This is exactly why `SYSTEM_PROMPT_PATH` must come from
  `src/config.py` (which uses `Path(__file__).parent.parent` = project root) instead
  of being computed relative to the script.

- **cwd-relative paths** — all scripts currently assume they are run from the project
  root. `src/config.py` eliminates this assumption by anchoring all paths to
  `Path(__file__).parent.parent` (the project root), making the scripts
  cwd-independent.

- **ChromaDB path** — `CHROMA_PATH` is passed as a string to `chromadb.PersistentClient`.
  After the move it should be `str(ROOT / "chroma_store")` in `config.py` to ensure
  it resolves correctly regardless of cwd.

- **contextualized_chunks.db** — at ~300 MB this stays gitignored. The new path in
  config is still `ROOT / "contextualized_chunks.db"` (project root), so existing
  data is not invalidated by the restructure.
