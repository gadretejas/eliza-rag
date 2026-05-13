#!/usr/bin/env python3
"""
Hybrid retriever: metadata-filtered vector search + cross-encoder re-ranking.

Usage:
    from retrieve import HybridRetriever, RetrieverConfig

    retriever = HybridRetriever()
    results   = retriever.retrieve("What are NVDA's primary risk factors?")
    for r in results:
        print(r["ticker"], r["section_id"], r["score"])

CLI smoke-test:
    python retrieve.py "What are Apple and Tesla's biggest risk factors?"
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np

CHUNKS_PATH = Path("chunks.jsonl")
INDEX_PATH  = Path("index.faiss")

# ── Configuration ──────────────────────────────────────────────────────────────

@dataclass
class RetrieverConfig:
    chunks_path: Path = field(default_factory=lambda: CHUNKS_PATH)
    index_path:  Path = field(default_factory=lambda: INDEX_PATH)

    # Vector search
    candidates_per_company: int = 20   # ANN candidates retrieved per ticker
    candidates_global: int = 60        # candidates when no ticker filter
    oversample_factor:  int = 8        # multiply top_k before metadata post-filter

    # Re-ranking
    rerank: bool = True
    reranker: Literal["local", "cohere", "none"] = "local"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    cohere_model:   str = "rerank-english-v3.0"

    # Final selection
    top_k: int = 15
    # min_per_company: None = auto-compute as max(2, top_k // n_companies)
    min_per_company: int | None = None


# ── Query router ───────────────────────────────────────────────────────────────

# Maps lowercased company names / tickers → canonical ticker symbol.
# Sorted at module load time longest-first so longer phrases match before
# shorter substrings (e.g. "jp morgan" before "morgan").
_COMPANY_ALIASES: dict[str, str] = {
    "apple": "AAPL",          "aapl": "AAPL",
    "abbvie": "ABBV",         "abbv": "ABBV",
    "adobe": "ADBE",          "adbe": "ADBE",
    "advanced micro devices": "AMD", "amd": "AMD",
    "amazon": "AMZN",         "amzn": "AMZN",
    "american express": "AXP","amex": "AXP",   "axp": "AXP",
    "boeing": "BA",
    "bank of america": "BAC", "bac": "BAC",
    "blackrock": "BLK",       "blk": "BLK",
    "berkshire hathaway": "BRK", "berkshire": "BRK", "brk": "BRK",
    "caterpillar": "CAT",     "cat": "CAT",
    "comcast": "CMCSA",       "cmcsa": "CMCSA",
    "costco": "COST",         "cost": "COST",
    "salesforce": "CRM",      "crm": "CRM",
    "cisco": "CSCO",          "csco": "CSCO",
    "chevron": "CVX",         "cvx": "CVX",
    "john deere": "DE",       "deere": "DE",
    "disney": "DIS",          "walt disney": "DIS", "dis": "DIS",
    "general electric": "GE", "ge": "GE",
    "alphabet": "GOOG",       "google": "GOOG",  "goog": "GOOG",
    "goldman sachs": "GS",    "goldman": "GS",   "gs": "GS",
    "home depot": "HD",       "hd": "HD",
    "ibm": "IBM",
    "intel": "INTC",          "intc": "INTC",
    "johnson & johnson": "JNJ", "j&j": "JNJ",    "jnj": "JNJ",
    "jpmorgan chase": "JPM",  "jpmorgan": "JPM", "jp morgan": "JPM", "jpm": "JPM",
    "coca-cola": "KO",        "coca cola": "KO", "coke": "KO",       "ko": "KO",
    "eli lilly": "LLY",       "lilly": "LLY",    "lly": "LLY",
    "lockheed martin": "LMT", "lockheed": "LMT", "lmt": "LMT",
    "mastercard": "MA",       "ma": "MA",
    "mcdonalds": "MCD",       "mcdonald's": "MCD", "mcd": "MCD",
    "meta": "META",           "facebook": "META",
    "merck": "MRK",           "mrk": "MRK",
    "morgan stanley": "MS",   "ms": "MS",
    "microsoft": "MSFT",      "msft": "MSFT",
    "netflix": "NFLX",        "nflx": "NFLX",
    "nike": "NKE",            "nke": "NKE",
    "nvidia": "NVDA",         "nvda": "NVDA",
    "oracle": "ORCL",         "orcl": "ORCL",
    "pepsico": "PEP",         "pepsi": "PEP",   "pep": "PEP",
    "pfizer": "PFE",          "pfe": "PFE",
    "procter & gamble": "PG", "procter": "PG",  "p&g": "PG",
    "raytheon": "RTX",        "rtx": "RTX",
    "starbucks": "SBUX",      "sbux": "SBUX",
    "at&t": "T",              "att": "T",
    "target": "TGT",          "tgt": "TGT",
    "thermo fisher": "TMO",   "tmo": "TMO",
    "tesla": "TSLA",          "tsla": "TSLA",
    "unitedhealth": "UNH",    "united health": "UNH", "unh": "UNH",
    "ups": "UPS",             "united parcel": "UPS",
    "visa": "V",
    "verizon": "VZ",          "vz": "VZ",
    "walmart": "WMT",         "wal-mart": "WMT", "wmt": "WMT",
    "exxonmobil": "XOM",      "exxon": "XOM",   "xom": "XOM",
}
# Pre-sort longest alias first to avoid partial-match shadowing
_SORTED_ALIASES = sorted(_COMPANY_ALIASES.items(), key=lambda x: -len(x[0]))

# Signal words → section IDs. Listed in priority order; first match wins for
# the primary section. A question can match multiple groups.
_SECTION_SIGNALS: list[tuple[list[str], list[str]]] = [
    (
        ["Item 1A"],
        ["risk factor", "risk factors", "risks", "risk", "exposure", "threat",
         "vulnerability", "uncertainty", "hazard", "concern"],
    ),
    (
        ["Item 7", "Item 8"],
        ["revenue", "sales", "growth", "outlook", "guidance", "forecast",
         "performance", "results", "earnings", "profit", "income", "margin",
         "eps", "ebitda", "cash flow", "operating income", "net income",
         "quarterly results", "annual results", "financial results"],
    ),
    (
        ["Item 1A", "Item 1"],
        ["regulatory", "regulation", "compliance", "fda", "antitrust",
         "legislation", "government", "policy", "sec enforcement", "litigation",
         "lawsuit"],
    ),
    (
        ["Item 1"],
        ["business", "operations", "products", "services", "segment",
         "overview", "business model", "competition", "industry"],
    ),
    (
        ["Item 7"],
        ["management", "mda", "discussion", "analysis", "liquidity",
         "capital allocation", "working capital", "strategy"],
    ),
]

_DEFAULT_SECTIONS = ["Item 1A", "Item 1", "Item 7"]

# Temporal language → (days_back,) or (year_string,)
_TEMPORAL_PATTERNS: list[tuple[str, int]] = [
    (r"\blast\s+two\s+years?\b",   730),
    (r"\bpast\s+two\s+years?\b",   730),
    (r"\blast\s+three\s+years?\b", 1095),
    (r"\blast\s+year\b",           365),
    (r"\bpast\s+year\b",           365),
    (r"\brecently\b",              365),
    (r"\brecent\b",                365),
    (r"\bthis\s+year\b",           180),
    (r"\bcurrent\b",               180),
    (r"\blatest\b",                365),
]


@dataclass
class RouteResult:
    tickers:      list[str]
    sections:     list[str]
    date_from:    str | None    # ISO-8601 date string or None
    filing_type:  str | None    # "10-K" | "10-Q" | None


class QueryRouter:
    """Converts a natural-language question into structured retrieval filters."""

    def route(self, question: str) -> RouteResult:
        return RouteResult(
            tickers=self._extract_tickers(question),
            sections=self._extract_sections(question),
            date_from=self._extract_date_from(question),
            filing_type=self._extract_filing_type(question),
        )

    # ── private helpers ────────────────────────────────────────────────────────

    def _extract_tickers(self, question: str) -> list[str]:
        q = question.lower()
        found: set[str] = set()
        for alias, ticker in _SORTED_ALIASES:
            if re.search(r"\b" + re.escape(alias) + r"\b", q):
                found.add(ticker)
        return sorted(found)

    def _extract_sections(self, question: str) -> list[str]:
        q = question.lower()
        sections: set[str] = set()
        for section_ids, keywords in _SECTION_SIGNALS:
            if any(kw in q for kw in keywords):
                sections.update(section_ids)
        return sorted(sections) if sections else list(_DEFAULT_SECTIONS)

    def _extract_date_from(self, question: str) -> str | None:
        q = question.lower()
        for pattern, days_back in _TEMPORAL_PATTERNS:
            if re.search(pattern, q):
                d = date.today() - timedelta(days=days_back)
                return d.isoformat()
        # Explicit year mention: "in 2023", "since 2024"
        m = re.search(r"\b(20\d{2})\b", q)
        if m:
            return f"{m.group(1)}-01-01"
        return None

    def _extract_filing_type(self, question: str) -> str | None:
        q = question.lower()
        if "annual" in q or "10-k" in q or "10k" in q:
            return "10-K"
        if "quarterly" in q or "10-q" in q or "10q" in q:
            return "10-Q"
        return None


# ── Vector index ───────────────────────────────────────────────────────────────

class VectorIndex:
    """
    Wraps a FAISS IndexFlatIP.
    Chunks are loaded into memory on init for fast metadata post-filtering.
    """

    def __init__(self, chunks_path: Path, index_path: Path) -> None:
        try:
            import faiss
        except ImportError:
            sys.exit("faiss-cpu not installed — run: pip install faiss-cpu")

        if not index_path.exists():
            sys.exit(
                f"{index_path} not found — run embed.py first to build the index."
            )
        if not chunks_path.exists():
            sys.exit(f"{chunks_path} not found — run chunk.py first.")

        self._faiss = faiss.read_index(str(index_path))

        self._chunks: list[dict[str, Any]] = []
        with chunks_path.open(encoding="utf-8") as f:
            for line in f:
                self._chunks.append(json.loads(line))

        if self._faiss.ntotal != len(self._chunks):
            raise ValueError(
                f"Index has {self._faiss.ntotal} vectors but "
                f"{len(self._chunks)} chunks — rebuild with embed.py."
            )

    def search(
        self,
        query_vec: np.ndarray,
        filters: dict[str, Any],
        top_k: int,
        oversample_factor: int = 8,
    ) -> list[tuple[float, dict]]:
        """
        Return up to top_k (score, chunk) pairs matching filters.
        Performs ANN search on top_k * oversample_factor candidates then
        post-filters by metadata.  Falls back gracefully if filters are too
        strict (relaxes date first, then section).
        """
        n_search = min(top_k * oversample_factor, self._faiss.ntotal)
        qv = query_vec.reshape(1, -1).astype(np.float32)

        scores, indices = self._faiss.search(qv, n_search)

        results = self._apply_filters(scores[0], indices[0], filters, top_k)

        # Fallback 1: relax date filter
        if len(results) < max(1, top_k // 2) and filters.get("date_from"):
            relaxed = {**filters, "date_from": None}
            results = self._apply_filters(scores[0], indices[0], relaxed, top_k)

        # Fallback 2: relax section filter
        if len(results) < max(1, top_k // 2) and filters.get("sections"):
            relaxed = {**filters, "sections": None, "date_from": None}
            results = self._apply_filters(scores[0], indices[0], relaxed, top_k)

        return results

    # ── helpers ────────────────────────────────────────────────────────────────

    def _apply_filters(
        self,
        scores: np.ndarray,
        indices: np.ndarray,
        filters: dict[str, Any],
        top_k: int,
    ) -> list[tuple[float, dict]]:
        results: list[tuple[float, dict]] = []
        for score, idx in zip(scores, indices):
            if idx < 0:
                continue
            chunk = self._chunks[int(idx)]
            if self._matches(chunk, filters):
                results.append((float(score), chunk))
                if len(results) >= top_k:
                    break
        return results

    @staticmethod
    def _matches(chunk: dict, filters: dict[str, Any]) -> bool:
        if filters.get("tickers") and chunk["ticker"] not in filters["tickers"]:
            return False
        if filters.get("sections") and chunk["section_id"] not in filters["sections"]:
            return False
        if filters.get("date_from") and chunk["filing_date"] < filters["date_from"]:
            return False
        if filters.get("filing_type"):
            ft = filters["filing_type"]
            if not chunk["filing_type"].startswith(ft):
                return False
        # Skip table chunks by default to keep context cleaner
        if filters.get("text_only") and chunk["content_type"] == "table":
            return False
        return True


# ── Re-ranker ──────────────────────────────────────────────────────────────────

class Reranker:
    """
    Wraps a cross-encoder for (question, chunk_text) scoring.
    Model is lazy-loaded on first call.
    """

    def __init__(self, backend: str, model_name: str, cohere_model: str) -> None:
        self._backend      = backend
        self._model_name   = model_name
        self._cohere_model = cohere_model
        self._model        = None   # lazy-loaded

    def rerank(
        self,
        question: str,
        candidates: list[tuple[float, dict]],
    ) -> list[tuple[float, dict]]:
        """Return candidates sorted by cross-encoder score (descending)."""
        if self._backend == "none" or not candidates:
            return candidates

        texts = [c["text"] for _, c in candidates]

        if self._backend == "local":
            scores = self._score_local(question, texts)
        elif self._backend == "cohere":
            scores = self._score_cohere(question, texts)
        else:
            return candidates

        scored = sorted(
            zip(scores, [c for _, c in candidates]),
            key=lambda x: x[0],
            reverse=True,
        )
        return scored

    # ── backends ───────────────────────────────────────────────────────────────

    def _score_local(self, question: str, texts: list[str]) -> list[float]:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError:
                sys.exit(
                    "sentence-transformers not installed — "
                    "run: pip install sentence-transformers"
                )
            self._model = CrossEncoder(self._model_name)
        pairs  = [[question, t] for t in texts]
        scores = self._model.predict(pairs)
        return scores.tolist()

    def _score_cohere(self, question: str, texts: list[str]) -> list[float]:
        if self._model is None:
            try:
                import cohere
            except ImportError:
                sys.exit("cohere not installed — run: pip install cohere")
            api_key = os.environ.get("COHERE_API_KEY")
            if not api_key:
                sys.exit("COHERE_API_KEY environment variable not set.")
            self._model = cohere.ClientV2(api_key=api_key)

        resp   = self._model.rerank(
            model=self._cohere_model,
            query=question,
            documents=texts,
        )
        scores = [0.0] * len(texts)
        for r in resp.results:
            scores[r.index] = r.relevance_score
        return scores


# ── Balancing ──────────────────────────────────────────────────────────────────

def _balance(
    ranked: list[tuple[float, dict]],
    tickers: list[str],
    top_k: int,
    min_per: int,
) -> list[tuple[float, dict]]:
    """
    Ensure at least min_per chunks per mentioned ticker, fill remaining
    slots with the highest-scored chunks across all companies.
    """
    per_company: dict[str, list[tuple[float, dict]]] = {t: [] for t in tickers}
    overflow: list[tuple[float, dict]] = []

    for score, chunk in ranked:
        t = chunk["ticker"]
        if t in per_company and len(per_company[t]) < min_per:
            per_company[t].append((score, chunk))
        else:
            overflow.append((score, chunk))

    result = [item for items in per_company.values() for item in items]
    remaining = top_k - len(result)
    result.extend(overflow[:remaining])

    # Re-sort by score so the LLM sees highest-relevance chunks first
    result.sort(key=lambda x: x[0], reverse=True)
    return result[:top_k]


# ── Retrieval trace ────────────────────────────────────────────────────────────

@dataclass
class RetrievalTrace:
    question:        str
    route:           RouteResult
    n_candidates:    int
    n_after_rerank:  int
    final_chunks:    list[dict]
    scores:          list[float]


# ── Hybrid retriever ───────────────────────────────────────────────────────────

class HybridRetriever:
    """
    Single-shot retrieval pipeline:
        query router → metadata-filtered ANN search → cross-encoder re-rank
        → per-company balancing → top-k chunks
    """

    def __init__(self, config: RetrieverConfig | None = None) -> None:
        self.config   = config or RetrieverConfig()
        self._index   = None    # lazy-loaded
        self._reranker: Reranker | None = None
        self._router  = QueryRouter()
        self._embedder = None   # lazy-loaded

    # ── public API ─────────────────────────────────────────────────────────────

    def retrieve(self, question: str) -> list[dict]:
        """Return top-k chunks as plain dicts with a 'score' field added."""
        trace = self._retrieve_traced(question)
        return trace.final_chunks

    def retrieve_with_trace(self, question: str) -> RetrievalTrace:
        """Same as retrieve() but also returns diagnostic information."""
        return self._retrieve_traced(question)

    # ── internals ──────────────────────────────────────────────────────────────

    def _retrieve_traced(self, question: str) -> RetrievalTrace:
        cfg   = self.config
        route = self._router.route(question)

        # ── embed query ───────────────────────────────────────────────────────
        qvec = self._embed(question)

        # ── per-ticker ANN search ─────────────────────────────────────────────
        index    = self._get_index()
        base_filters = {
            "sections":     route.sections or None,
            "date_from":    route.date_from,
            "filing_type":  route.filing_type,
            "text_only":    True,
        }

        candidates: list[tuple[float, dict]] = []

        if route.tickers:
            for ticker in route.tickers:
                filters = {**base_filters, "tickers": [ticker]}
                hits = index.search(
                    qvec, filters,
                    top_k=cfg.candidates_per_company,
                    oversample_factor=cfg.oversample_factor,
                )
                candidates.extend(hits)
        else:
            candidates = index.search(
                qvec, base_filters,
                top_k=cfg.candidates_global,
                oversample_factor=cfg.oversample_factor,
            )

        n_candidates = len(candidates)

        # ── re-rank ───────────────────────────────────────────────────────────
        if cfg.rerank and cfg.reranker != "none":
            ranked = self._get_reranker().rerank(question, candidates)
        else:
            ranked = sorted(candidates, key=lambda x: x[0], reverse=True)

        # ── per-company balancing ─────────────────────────────────────────────
        if route.tickers:
            min_per = cfg.min_per_company or max(2, cfg.top_k // len(route.tickers))
            ranked  = _balance(ranked, route.tickers, cfg.top_k, min_per)
        else:
            ranked = ranked[: cfg.top_k]

        # ── attach scores and return ──────────────────────────────────────────
        final: list[dict] = []
        scores: list[float] = []
        for score, chunk in ranked:
            enriched = {**chunk, "score": round(score, 4)}
            final.append(enriched)
            scores.append(round(score, 4))

        return RetrievalTrace(
            question=question,
            route=route,
            n_candidates=n_candidates,
            n_after_rerank=len(ranked),
            final_chunks=final,
            scores=scores,
        )

    # ── lazy loaders ──────────────────────────────────────────────────────────

    def _get_index(self) -> VectorIndex:
        if self._index is None:
            self._index = VectorIndex(self.config.chunks_path, self.config.index_path)
        return self._index

    def _get_reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = Reranker(
                self.config.reranker,
                self.config.reranker_model,
                self.config.cohere_model,
            )
        return self._reranker

    def _embed(self, text: str) -> np.ndarray:
        if self._embedder is None:
            self._embedder = _load_embedder()
        return self._embedder(text)


# ── Embedder factory ───────────────────────────────────────────────────────────

def _load_embedder():
    """
    Auto-detect the embedding backend from the FAISS index dimension.
    Falls back to local model if OPENAI_API_KEY is not set.
    """
    try:
        import faiss
        if not INDEX_PATH.exists():
            raise FileNotFoundError
        idx = faiss.read_index(str(INDEX_PATH))
        dim = idx.d
    except Exception:
        dim = None

    if dim == 1536 and os.environ.get("OPENAI_API_KEY"):
        return _make_openai_embedder()
    else:
        return _make_local_embedder()


def _make_openai_embedder():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai not installed — run: pip install openai")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def embed(text: str) -> np.ndarray:
        resp = client.embeddings.create(
            input=[text],
            model="text-embedding-3-small",
        )
        vec = np.array(resp.data[0].embedding, dtype=np.float32)
        vec /= max(np.linalg.norm(vec), 1e-9)
        return vec

    return embed


def _make_local_embedder():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit("sentence-transformers not installed — run: pip install sentence-transformers")

    model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed(text: str) -> np.ndarray:
        vec = model.encode([text], normalize_embeddings=False)[0].astype(np.float32)
        norm = np.linalg.norm(vec)
        return vec / max(norm, 1e-9)

    return embed


# ── CLI smoke-test ─────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run a retrieval query")
    parser.add_argument("question", help="Natural language question")
    parser.add_argument("--top-k",   type=int, default=15)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--reranker", choices=["local", "cohere", "none"], default="local")
    parser.add_argument("--trace",   action="store_true", help="Print routing + score info")
    args = parser.parse_args()

    config = RetrieverConfig(
        top_k=args.top_k,
        rerank=not args.no_rerank,
        reranker=args.reranker,
    )
    retriever = HybridRetriever(config)
    trace     = retriever.retrieve_with_trace(args.question)

    if args.trace:
        r = trace.route
        print(f"\n── Route ────────────────────────────────────")
        print(f"  Tickers   : {r.tickers or '(all)'}")
        print(f"  Sections  : {r.sections}")
        print(f"  Date from : {r.date_from or '(none)'}")
        print(f"  Filing    : {r.filing_type or '(any)'}")
        print(f"  Candidates: {trace.n_candidates}")
        print(f"  Returned  : {len(trace.final_chunks)}")

    print(f"\n── Results for: {args.question!r} ──")
    for i, chunk in enumerate(trace.final_chunks, 1):
        print(
            f"\n[{i}] {chunk['ticker']} · {chunk['filing_type'][:4]} "
            f"· {chunk['filing_date']} · {chunk['section_id']} "
            f"· score={chunk['score']:.4f}"
        )
        print(f"     {chunk['text'][:200].replace(chr(10), ' ')} ...")


if __name__ == "__main__":
    main()
