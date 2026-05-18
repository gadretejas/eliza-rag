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

import os
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from src.config import (
    CHROMA_PATH, COLLECTION_NAME,
    OPENAI_EMBED_MODEL, LOCAL_EMBED_MODEL,
)

# Maps the short filing_type used by QueryRouter to the full stored value
_FILING_TYPE_MAP = {
    "10-K": "10-K (Annual Report)",
    "10-Q": "10-Q (Quarterly Report)",
}

# ── Configuration ──────────────────────────────────────────────────────────────

@dataclass
class RetrieverConfig:
    chroma_path:       str = CHROMA_PATH
    chroma_collection: str = COLLECTION_NAME

    # Vector search
    candidates_per_company: int = 35
    candidates_global: int = 80
    oversample_factor:  int = 8

    # Re-ranking
    rerank: bool = True
    reranker: Literal["local", "cohere", "none"] = "none"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    cohere_model:   str = "rerank-english-v3.0"

    # Final selection
    top_k: int = 15
    min_per_company: int | None = None

    # RBAC — restrict retrieval to a specific set of tickers.
    # None means no restriction (all companies accessible).
    allowed_tickers: list[str] | None = None


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

# Corpus context injected into the routing LLM call so it can resolve industry
# terms and category questions (e.g. "pharmaceutical companies") to tickers.
_CORPUS_CONTEXT = """\
The SEC filings corpus contains these companies, grouped by sector:

Technology:        AAPL (Apple), MSFT (Microsoft), NVDA (NVIDIA), META (Meta/Facebook),
                   GOOG (Alphabet/Google), AMZN (Amazon), AMD, INTC (Intel),
                   ADBE (Adobe), ORCL (Oracle), CRM (Salesforce), CSCO (Cisco),
                   IBM, NFLX (Netflix)
Semiconductors:    NVDA (NVIDIA), AMD, INTC (Intel)
Healthcare/Pharma: PFE (Pfizer), JNJ (Johnson & Johnson), MRK (Merck),
                   LLY (Eli Lilly), ABBV (AbbVie), UNH (UnitedHealth), TMO (Thermo Fisher)
Financial/Banking: JPM (JPMorgan Chase), GS (Goldman Sachs), MS (Morgan Stanley),
                   BAC (Bank of America), BLK (BlackRock), AXP (American Express),
                   MA (Mastercard), V (Visa), BRK (Berkshire Hathaway)
Energy:            XOM (ExxonMobil), CVX (Chevron)
Consumer/Retail:   WMT (Walmart), COST (Costco), MCD (McDonald's), SBUX (Starbucks),
                   KO (Coca-Cola), PEP (PepsiCo), TGT (Target), NKE (Nike),
                   PG (Procter & Gamble), HD (Home Depot)
Media/Entertainment: DIS (Disney), NFLX (Netflix), CMCSA (Comcast)
Industrial/Defense: CAT (Caterpillar), DE (John Deere), BA (Boeing),
                    RTX (Raytheon), LMT (Lockheed Martin), GE
Telecom:           T (AT&T), VZ (Verizon), CMCSA (Comcast)
Automotive:        TSLA (Tesla)
"""

# Signal words → section IDs. Listed in priority order; first match wins for
# the primary section. A question can match multiple groups.
_SECTION_SIGNALS: list[tuple[list[str], list[str]]] = [
    (
        ["Item 1A"],
        ["risk factor", "risk factors", "risks", "risk", "exposure", "threat",
         "vulnerability", "uncertainty", "hazard", "concern"],
    ),
    (
        # Item 7/8 = MD&A/financials in 10-K; Item 2/1 = same in 10-Q
        ["Item 7", "Item 8", "Item 2"],
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
        # Item 7 = MD&A in 10-K; Item 2 = MD&A in 10-Q
        ["Item 7", "Item 2"],
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
    date_to:      str | None    # ISO-8601 date string or None (None = open-ended)
    filing_type:  str | None    # "10-K" | "10-Q" | None


class QueryRouter:
    """Converts a natural-language question into structured retrieval filters."""

    def __init__(self) -> None:
        self._llm_client: Any | None = None
        if os.environ.get("OPENAI_API_KEY"):
            try:
                from openai import OpenAI
                self._llm_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            except ImportError:
                pass

    def route(self, question: str) -> RouteResult:
        date_from, date_to = self._extract_date_range(question)
        return RouteResult(
            tickers=self._extract_tickers(question),
            sections=self._extract_sections(question),
            date_from=date_from,
            date_to=date_to,
            filing_type=self._extract_filing_type(question),
        )

    # ── private helpers ────────────────────────────────────────────────────────

    def _extract_tickers(self, question: str) -> list[str]:
        # Fast path: regex match against known aliases
        q = question.lower()
        found: set[str] = set()
        for alias, ticker in _SORTED_ALIASES:
            if re.search(r"\b" + re.escape(alias) + r"\b", q):
                found.add(ticker)
        if found:
            return sorted(found)

        # Slow path: LLM call to resolve industry/category terms when no
        # specific company name was found (e.g. "pharmaceutical companies").
        if self._llm_client is None:
            return []

        import json as _json
        try:
            resp = self._llm_client.chat.completions.create(
                model="gpt-5.4-mini",
                temperature=0,
                max_completion_tokens=64,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{_CORPUS_CONTEXT}\n"
                            "Your job is to identify which company tickers from the corpus "
                            "are relevant to a user question. Return ONLY a JSON array of "
                            "ticker symbols (e.g. [\"PFE\",\"JNJ\"]). If the question is "
                            "general and not about specific companies or sectors, return []."
                        ),
                    },
                    {"role": "user", "content": question},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            tickers = _json.loads(raw)
            if isinstance(tickers, list):
                # Validate against known corpus tickers
                valid = set(_COMPANY_ALIASES.values())
                return sorted(t for t in tickers if t in valid)
        except Exception:
            pass
        return []

    def _extract_sections(self, question: str) -> list[str]:
        q = question.lower()
        sections: set[str] = set()
        for section_ids, keywords in _SECTION_SIGNALS:
            if any(kw in q for kw in keywords):
                sections.update(section_ids)
        return sorted(sections) if sections else list(_DEFAULT_SECTIONS)

    def _extract_date_range(self, question: str) -> tuple[str | None, str | None]:
        """Return (date_from, date_to) ISO strings. Both None if no temporal signal."""
        q = question.lower()

        # Relative phrases → open-ended floor (date_from only, no ceiling)
        for pattern, days_back in _TEMPORAL_PATTERNS:
            if re.search(pattern, q):
                d = date.today() - timedelta(days=days_back)
                return d.isoformat(), None

        # Explicit year mention → closed window for that calendar year.
        # "since YYYY" / "from YYYY" → floor only (no ceiling).
        # "as of YYYY" / "in YYYY" / "fiscal YYYY" / bare year → full year window.
        m = re.search(r"\b(20\d{2})\b", q)
        if m:
            year = m.group(1)
            open_ended = bool(re.search(r"\b(since|from)\b", q))
            date_from = f"{year}-01-01"
            date_to   = None if open_ended else f"{year}-12-31"
            return date_from, date_to

        return None, None

    def _extract_filing_type(self, question: str) -> str | None:
        q = question.lower()
        if "annual" in q or "10-k" in q or "10k" in q:
            return "10-K"
        if "quarterly" in q or "10-q" in q or "10q" in q:
            return "10-Q"
        # Risk factor questions → prefer 10-K (10-Qs say "no material changes")
        sections = self._extract_sections(question)
        if sections == ["Item 1A"]:
            return "10-K"
        return None


# ── Vector index ───────────────────────────────────────────────────────────────

class VectorIndex:
    """
    Wraps a ChromaDB collection.
    Metadata filtering happens inside the DB; three-level fallback mirrors
    the previous FAISS post-filter approach.
    """

    def __init__(self, chroma_path: str, collection_name: str) -> None:
        try:
            import chromadb
        except ImportError:
            sys.exit("chromadb not installed — run: pip install chromadb")

        client = chromadb.PersistentClient(path=chroma_path)
        try:
            self._collection = client.get_collection(collection_name)
        except Exception:
            sys.exit(
                f"ChromaDB collection '{collection_name}' not found in {chroma_path}/ — "
                "run embed.py first."
            )

    def search(
        self,
        query_vec: np.ndarray,
        filters: dict[str, Any],
        top_k: int,
        oversample_factor: int = 8,
    ) -> list[tuple[float, dict]]:
        n_results = top_k * oversample_factor

        # Three-level fallback: full filters → relax date → relax section+date
        for where in self._fallback_wheres(filters):
            results = self._query(query_vec, where, n_results)
            if len(results) >= max(1, top_k // 2):
                return results[:top_k]

        return results[:top_k]

    # ── helpers ────────────────────────────────────────────────────────────────

    def _query(
        self,
        query_vec: np.ndarray,
        where: dict | None,
        n_results: int,
    ) -> list[tuple[float, dict]]:
        total = self._collection.count()
        if total == 0:
            return []

        n = min(n_results, total)
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_vec.tolist()],
            "n_results":        n,
            "include":          ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        # ChromaDB raises when n_results exceeds the number of items matching
        # the where clause. Retry with halved n until it succeeds rather than
        # returning [] and silently falling through to the no-filter fallback.
        while n >= 1:
            kwargs["n_results"] = n
            try:
                r = self._collection.query(**kwargs)
                break
            except Exception as exc:
                msg = str(exc).lower()
                if "n_results" in msg or "number of elements" in msg or "brute" in msg:
                    n = n // 2
                else:
                    return []
        else:
            return []

        results = []
        for doc, meta, dist in zip(
            r["documents"][0], r["metadatas"][0], r["distances"][0]
        ):
            score = 1.0 - dist
            chunk = {"text": doc, **meta}
            results.append((score, chunk))

        return results

    def _fallback_wheres(self, filters: dict[str, Any]):
        """Yield progressively looser where clauses.

        Date filtering is handled in Python post-retrieval, not here.
        Level 1: ticker + section filter
        Level 2: ticker only (drop section)
        Level 3: no filter (last resort)
        """
        yield self._build_where(filters)

        if filters.get("sections"):
            yield self._build_where({**filters, "sections": None})

        yield None

    @staticmethod
    def _build_where(filters: dict[str, Any]) -> dict | None:
        conditions = []

        tickers = filters.get("tickers")
        if tickers:
            conditions.append({"ticker": {"$in": tickers}})

        sections = filters.get("sections")
        if sections:
            conditions.append({"section_id": {"$in": sections}})

        # NOTE: ChromaDB $gte/$lte only support numeric operands, not strings.
        # Date filtering is handled in Python post-retrieval via _apply_date_filter.

        filing_type = filters.get("filing_type")
        if filing_type:
            full = _FILING_TYPE_MAP.get(filing_type, filing_type)
            conditions.append({"filing_type": {"$eq": full}})

        if filters.get("text_only"):
            conditions.append({"content_type": {"$eq": "text"}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}


# ── Date filtering helpers ─────────────────────────────────────────────────────

def _widen_date_window(filters: dict[str, Any], years: int) -> dict[str, Any]:
    """Return a copy of filters with the date window expanded by ±N years."""
    result = dict(filters)

    if filters.get("date_from"):
        try:
            d = date.fromisoformat(filters["date_from"])
            result["date_from"] = date(d.year - years, d.month, d.day).isoformat()
        except (ValueError, OverflowError):
            pass

    if filters.get("date_to"):
        try:
            d = date.fromisoformat(filters["date_to"])
            widened = date(d.year + years, d.month, d.day)
            result["date_to"] = min(widened, date.today()).isoformat()
        except (ValueError, OverflowError):
            result["date_to"] = date.today().isoformat()

    return result


def _apply_date_filter(
    candidates: list[tuple[float, dict]],
    date_from:  str | None,
    date_to:    str | None,
) -> list[tuple[float, dict]]:
    """Hard-filter candidates to the intended date window."""
    if not date_from and not date_to:
        return candidates
    result = []
    for score, chunk in candidates:
        fd = chunk.get("filing_date", "")
        if (not date_from or fd >= date_from) and (not date_to or fd <= date_to):
            result.append((score, chunk))
    return result


def _apply_date_penalty(
    candidates: list[tuple[float, dict]],
    date_from:  str | None,
    date_to:    str | None,
    penalty:    float = 0.40,
) -> list[tuple[float, dict]]:
    """Discount chunks outside the intended date window without hard-excluding them.

    A penalty of 0.40 means an out-of-window chunk needs a raw score >2.5×
    higher than an in-window chunk to still win — effectively ruling it out
    in practice while keeping the fallback for truly sparse windows.
    """
    if not date_from and not date_to:
        return candidates

    result = []
    for score, chunk in candidates:
        fd = chunk.get("filing_date", "")
        in_window = (
            (not date_from or fd >= date_from) and
            (not date_to   or fd <= date_to)
        )
        result.append((score * penalty if not in_window else score, chunk))

    return sorted(result, key=lambda x: x[0], reverse=True)


_RECENCY_DECAY = 0.95  # score multiplier per year of filing age


def _apply_recency_preference(
    candidates: list[tuple[float, dict]],
) -> list[tuple[float, dict]]:
    """Gently prefer newer filings when no explicit date was requested.

    Applies 0.95^years_old to each chunk's score so a 3-year-old chunk needs
    to be meaningfully more relevant (not just a marginal tie) to beat a current one.
    """
    today = date.today()
    result = []
    for score, chunk in candidates:
        try:
            fd = date.fromisoformat(chunk.get("filing_date", ""))
            years_old = (today - fd).days / 365.25
            score = score * (_RECENCY_DECAY ** years_old)
        except (ValueError, TypeError):
            pass
        result.append((score, chunk))
    return result


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
            "date_to":      route.date_to,
            "filing_type":  route.filing_type,
            "text_only":    False,
        }

        candidates: list[tuple[float, dict]] = []

        # RBAC: intersect router tickers with the user's allowed_tickers.
        # If no router tickers, restrict global search to allowed_tickers.
        effective_tickers = route.tickers
        if cfg.allowed_tickers is not None:
            allowed_set = set(cfg.allowed_tickers)
            if effective_tickers:
                effective_tickers = [t for t in effective_tickers if t in allowed_set]
            else:
                effective_tickers = list(allowed_set)

        # When a date window is active, the semantically top-N chunks may all
        # come from older filings (they can be more verbose / better matches).
        # Request many more candidates so that the Python date-filter stage has
        # a large enough pool and can find recent chunks that rank lower on
        # pure semantic similarity.
        search_k_per_company = cfg.candidates_per_company
        search_k_global      = cfg.candidates_global
        if route.date_from or route.date_to:
            search_k_per_company = min(search_k_per_company * 6, 300)
            search_k_global      = min(search_k_global * 4, 500)

        if effective_tickers:
            for ticker in effective_tickers:
                filters = {**base_filters, "tickers": [ticker]}
                hits = index.search(
                    qvec, filters,
                    top_k=search_k_per_company,
                    oversample_factor=cfg.oversample_factor,
                )
                candidates.extend(hits)
        else:
            candidates = index.search(
                qvec, base_filters,
                top_k=search_k_global,
                oversample_factor=cfg.oversample_factor,
            )

        # Deduplicate by chunk id — same chunk can appear from multiple
        # per-ticker fallback searches when filters are very loose.
        seen: set[str] = set()
        unique: list[tuple[float, dict]] = []
        for score, chunk in candidates:
            cid = chunk.get("id") or chunk.get("source_file", "") + str(chunk.get("chunk_index", ""))
            if cid not in seen:
                seen.add(cid)
                unique.append((score, chunk))
        candidates = unique

        n_candidates = len(candidates)

        # ── date filtering (Python post-filter — ChromaDB $gte/$lte are numeric-only)
        filtered = _apply_date_filter(candidates, route.date_from, route.date_to)
        # Use hard filter if we have at least top_k//3 results in the window (≥5).
        # If fewer, apply a strong penalty (0.40×) so out-of-window chunks are
        # heavily discounted even when they score higher on pure semantic similarity.
        if len(filtered) >= max(1, cfg.top_k // 3):
            candidates = filtered
        else:
            # Too few results in window — apply strong penalty instead of hard cut
            candidates = _apply_date_penalty(candidates, route.date_from, route.date_to,
                                             penalty=0.40)

        # ── recency preference (only when no explicit date in question) ───────
        if route.date_from is None and route.date_to is None:
            candidates = _apply_recency_preference(candidates)

        # ── re-rank ───────────────────────────────────────────────────────────
        if cfg.rerank and cfg.reranker != "none":
            ranked = self._get_reranker().rerank(question, candidates)
        else:
            ranked = sorted(candidates, key=lambda x: x[0], reverse=True)

        # ── per-company balancing ─────────────────────────────────────────────
        if route.tickers:
            min_per = cfg.min_per_company or max(2, cfg.top_k // len(effective_tickers))
            ranked  = _balance(ranked, effective_tickers, cfg.top_k, min_per)
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
            self._index = VectorIndex(
                self.config.chroma_path,
                self.config.chroma_collection,
            )
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
            self._embedder = _load_embedder(
                self.config.chroma_path, self.config.chroma_collection
            )
        return self._embedder(text)


# ── Embedder factory ───────────────────────────────────────────────────────────

def _load_embedder(
    chroma_path: str = CHROMA_PATH,
    collection_name: str = COLLECTION_NAME,
):
    """
    Auto-detect the embedding backend from ChromaDB collection metadata.
    Falls back to local model if OPENAI_API_KEY is not set.
    """
    model_name = None
    try:
        import chromadb
        client     = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_collection(collection_name)
        model_name = (collection.metadata or {}).get("embedding_model")
    except Exception:
        pass

    if model_name == "openai" and os.environ.get("OPENAI_API_KEY"):
        return _make_openai_embedder()
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
            model=OPENAI_EMBED_MODEL,
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

    model = SentenceTransformer(LOCAL_EMBED_MODEL)

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
    parser.add_argument("--reranker", choices=["local", "cohere", "none"], default="none")
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
        print(f"  Date from : {r.date_from or '(none)'}  →  {r.date_to or '(open)'}")
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
