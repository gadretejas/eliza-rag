"""
Central configuration — all paths and shared constants live here.
Every module imports from this file instead of defining its own hardcoded paths.

ROOT is anchored to the project root via Path(__file__), so all paths resolve
correctly regardless of the working directory the script is called from.
"""

from pathlib import Path

# Project root (parent of src/)
ROOT = Path(__file__).parent.parent

# ── Data artifacts ─────────────────────────────────────────────────────────────
CORPUS_DIR        = ROOT / "edgar_corpus"
CHUNKS_PATH       = ROOT / "chunks.jsonl"
CACHE_PATH        = ROOT / "contexts_cache.json"
CONTEXTUALIZED_DB = ROOT / "contextualized_chunks.db"
CHROMA_PATH       = str(ROOT / "chroma_store")

# ── Test artifacts ─────────────────────────────────────────────────────────────
TEST_DB_PATH      = ROOT / "contextualization_test_output.db"

# ── ChromaDB collection names ──────────────────────────────────────────────────
COLLECTION_NAME      = "sec_filings"
TEST_COLLECTION_NAME = "sec_filings_test"

# ── Embedding models ───────────────────────────────────────────────────────────
OPENAI_EMBED_MODEL = "text-embedding-3-small"
LOCAL_EMBED_MODEL  = "all-MiniLM-L6-v2"

# ── LLM ───────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"

# ── Prompts ────────────────────────────────────────────────────────────────────
PROMPTS_DIR        = ROOT / "prompts"
SYSTEM_PROMPT_PATH         = PROMPTS_DIR / "system_prompt.md"
FOLLOWUP_SYSTEM_PROMPT_PATH = PROMPTS_DIR / "followup_system_prompt.md"

# ── Logs ───────────────────────────────────────────────────────────────────────
CONTEXTUALIZE_LOG = ROOT / "contextualize.log"
EMBED_LOG         = ROOT / "embed.log"
