#!/usr/bin/env python3
"""
Answer generation: retrieves relevant chunks and calls an LLM to produce
a grounded, cited answer over SEC EDGAR filings.

Usage:
    python answer.py "What are NVDA's primary risk factors?"
    python answer.py "Compare Apple and Tesla revenue" --model gpt-5.4
    python answer.py "MSFT cloud risks" --model ollama:llama3.2 --trace
    python answer.py "AAPL revenue 2023" --top-k 20 --model gpt-5.4-mini
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from src.retrieval.retrieve import HybridRetriever, RetrieverConfig, RetrievalTrace
from src.config import SYSTEM_PROMPT_PATH, CORPUS_DIR, OLLAMA_BASE_URL, OPENAI_BASE_URL

DEFAULT_MODEL    = "gpt-5.4-mini"
OLLAMA_FALLBACK  = "llama3.2"


# ── Configuration ──────────────────────────────────────────────────────────────

@dataclass
class AnswerConfig:
    model:           str   = DEFAULT_MODEL
    temperature:     float = 0.2
    max_tokens:      int   = 1024
    top_k:           int   = 15
    max_chunk_chars: int   = 2000     # guards context overflow on smaller models
    retriever_config: RetrieverConfig = field(default_factory=RetrieverConfig)
    # Custom provider fields (None → use env defaults)
    provider:  str | None = None      # "openai" | "anthropic" | "local"
    api_key:   str | None = None
    base_url:  str | None = None
    # RBAC — restrict retrieval to these tickers (None = unrestricted)
    allowed_tickers: list[str] | None = None


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class Citation:
    index:        int
    ticker:       str
    filing_type:  str
    filing_date:  str
    section_id:   str
    section_name: str
    passage_text: str
    source_file:  str     # filename within edgar_corpus/


@dataclass
class Answer:
    question:        str
    answer_text:     str            # LLM output with [n] markers intact
    citations:       list[Citation]
    model_used:      str
    n_chunks_used:   int
    retrieval_trace: RetrievalTrace | None = None


# ── LLM client ─────────────────────────────────────────────────────────────────

class LLMClient:
    """
    Unified LLM client supporting OpenAI, Anthropic, and local Llama (via Ollama).

    Provider resolution order:
        1. Explicit provider/api_key/base_url from AnswerConfig
        2. Legacy "ollama:<name>" model prefix → local
        3. OPENAI_API_KEY in environment → openai
        4. Fallback to local Ollama
    """

    def __init__(self, config: "AnswerConfig") -> None:
        model    = config.model
        provider = config.provider
        api_key  = config.api_key
        base_url = config.base_url

        # Legacy prefix support
        if model.startswith("ollama:") and provider is None:
            provider = "local"
            model    = model[len("ollama:"):]

        # Auto-detect provider when not explicitly set
        if provider is None:
            env_key = os.environ.get("OPENAI_API_KEY")
            if env_key:
                provider = "openai"
                api_key  = api_key or env_key
            else:
                print(
                    f"Warning: OPENAI_API_KEY not set — "
                    f"falling back to local Ollama ({OLLAMA_FALLBACK})",
                    file=sys.stderr,
                )
                provider = "local"
                model    = OLLAMA_FALLBACK

        self.model    = model
        self._provider = provider

        if provider == "anthropic":
            try:
                from anthropic import Anthropic
            except ImportError:
                sys.exit("anthropic not installed — run: pip install anthropic")
            self._anthropic = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
            self._openai    = None
        else:
            try:
                from openai import OpenAI
            except ImportError:
                sys.exit("openai not installed — run: pip install openai")
            if provider == "local":
                self._openai = OpenAI(
                    base_url=base_url or OLLAMA_BASE_URL,
                    api_key="ollama",
                )
            else:  # openai
                self._openai = OpenAI(
                    api_key=api_key or os.environ.get("OPENAI_API_KEY"),
                    **({"base_url": base_url} if base_url else {}),
                )
            self._anthropic = None

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        try:
            if self._provider == "anthropic":
                response = self._anthropic.messages.create(  # type: ignore[union-attr]
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return response.content[0].text  # type: ignore[union-attr]
            else:
                response = self._openai.chat.completions.create(  # type: ignore[union-attr]
                    model=self.model,
                    temperature=temperature,
                    max_completion_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                )
                return response.choices[0].message.content or ""
        except Exception as e:
            sys.exit(f"LLM call failed ({self._provider}/{self.model}): {e}")

    def stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        """Yield raw token strings as they arrive from the provider."""
        if self._provider == "anthropic":
            with self._anthropic.messages.stream(  # type: ignore[union-attr]
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as s:
                for text in s.text_stream:
                    yield text
        else:
            response = self._openai.chat.completions.create(  # type: ignore[union-attr]
                model=self.model,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                stream=True,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
            )
            for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta


# ── Prompt helpers ─────────────────────────────────────────────────────────────

def load_system_prompt(path: Path = SYSTEM_PROMPT_PATH) -> str:
    if not path.exists():
        sys.exit(f"System prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def build_prompt(question: str, chunks: list[dict], max_chunk_chars: int) -> str:
    """Format retrieved chunks as a numbered context block followed by the question."""
    lines = ["---"]
    for i, chunk in enumerate(chunks, start=1):
        # Shorten filing_type: "10-K (Annual Report)" → "10-K"
        filing_type = chunk["filing_type"].split()[0]
        header = (
            f"[{i}] {chunk['ticker']} · {filing_type} · "
            f"{chunk['filing_date']} · {chunk['section_id']}"
            + (f" — {chunk['section_name']}" if chunk.get("section_name") else "")
        )
        text = chunk["text"]
        if len(text) > max_chunk_chars:
            text = text[:max_chunk_chars] + " ..."
        lines.append(header)
        lines.append(text)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"Question: {question}")
    return "\n".join(lines)


# ── Citation parser ────────────────────────────────────────────────────────────

def parse_citations(
    answer_text: str,
    chunks: list[dict],
) -> tuple[str, list[Citation]]:
    """
    Extract [n] markers from answer_text, map each to a chunk, strip phantoms.
    Returns (cleaned_text, citations) where citations are deduplicated and
    ordered by first appearance.
    """
    referenced_indices = sorted(
        set(int(m) for m in re.findall(r"\[(\d+)\]", answer_text))
    )

    valid: set[int] = set()
    citations: list[Citation] = []

    for idx in referenced_indices:
        if 1 <= idx <= len(chunks):
            chunk = chunks[idx - 1]
            citations.append(Citation(
                index        = idx,
                ticker       = chunk["ticker"],
                filing_type  = chunk["filing_type"].split()[0],
                filing_date  = chunk["filing_date"],
                section_id   = chunk["section_id"],
                section_name = chunk.get("section_name", ""),
                passage_text = chunk["text"],
                source_file  = chunk.get("source_file", ""),
            ))
            valid.add(idx)

    # Remove phantom markers (indices outside 1..len(chunks))
    cleaned = re.sub(
        r"\[(\d+)\]",
        lambda m: f"[{m.group(1)}]" if int(m.group(1)) in valid else "",
        answer_text,
    )
    cleaned = re.sub(r"  +", " ", cleaned).strip()

    return cleaned, citations


# ── Answer engine ──────────────────────────────────────────────────────────────

class AnswerEngine:
    """
    Orchestrates: retrieve → build_prompt → LLM → parse_citations → Answer.
    All components are lazy-loaded on first use.
    """

    def __init__(self, config: AnswerConfig | None = None) -> None:
        self.config         = config or AnswerConfig()
        self._retriever:    HybridRetriever | None = None
        self._llm:          LLMClient | None       = None
        self._system_prompt: str | None            = None

    def answer(self, question: str) -> Answer:
        """Return a grounded Answer without retrieval trace."""
        return self._run(question, trace=False)

    def answer_with_trace(self, question: str) -> Answer:
        """Return a grounded Answer with RetrievalTrace attached."""
        return self._run(question, trace=True)

    def answer_stream(self, question: str) -> Iterator[dict]:
        """
        Yield SSE-ready dicts in order:
          {"type": "sources",   "sources": [...]}   ← emitted before LLM call
          {"type": "chunk",     "text": "..."}       ← one per token
          {"type": "citations", "valid": [1, 2, 3]}  ← after stream ends
          {"type": "done"}
        On failure yields {"type": "error", "detail": "..."} and stops.
        """
        cfg = self.config
        try:
            retrieval_trace = self._get_retriever().retrieve_with_trace(question)
            chunks = retrieval_trace.final_chunks
        except Exception as e:
            yield {"type": "error", "detail": f"Retrieval failed: {e}"}
            return

        # Emit sources immediately so the browser can render them before the
        # first token arrives.
        sources_payload = [
            {
                "index":       i + 1,
                "ticker":      c["ticker"],
                "filing_type": c["filing_type"].split()[0],
                "filing_date": c["filing_date"],
                "section":     c["section_id"],
                "snippet":     c["text"][:400],
            }
            for i, c in enumerate(chunks)
        ]
        yield {"type": "sources", "sources": sources_payload}

        if not chunks:
            yield {"type": "chunk", "text": (
                "The available filings do not contain enough information "
                "to answer this question."
            )}
            yield {"type": "citations", "valid": []}
            yield {"type": "done"}
            return

        user_message = build_prompt(question, chunks, cfg.max_chunk_chars)
        llm          = self._get_llm()
        accumulated  = ""

        try:
            for token in llm.stream(
                self._get_system_prompt(),
                user_message,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            ):
                accumulated += token
                yield {"type": "chunk", "text": token}
        except Exception as e:
            yield {"type": "error", "detail": f"LLM stream failed: {e}"}
            return

        # Parse citations from the full accumulated text.
        _, citations = parse_citations(accumulated, chunks)
        valid_indices = [c.index for c in citations]
        yield {"type": "citations", "valid": valid_indices}
        yield {"type": "done"}

    # ── internals ─────────────────────────────────────────────────────────────

    def _run(self, question: str, trace: bool) -> Answer:
        cfg = self.config

        retrieval_trace = self._get_retriever().retrieve_with_trace(question)
        chunks = retrieval_trace.final_chunks

        if not chunks:
            return Answer(
                question        = question,
                answer_text     = (
                    "The available filings do not contain enough information "
                    "to answer this question."
                ),
                citations       = [],
                model_used      = cfg.model,
                n_chunks_used   = 0,
                retrieval_trace = retrieval_trace if trace else None,
            )

        user_message = build_prompt(question, chunks, cfg.max_chunk_chars)
        llm          = self._get_llm()
        raw_answer   = llm.complete(
            self._get_system_prompt(),
            user_message,
            temperature = cfg.temperature,
            max_tokens  = cfg.max_tokens,
        )

        cleaned_answer, citations = parse_citations(raw_answer, chunks)

        return Answer(
            question        = question,
            answer_text     = cleaned_answer,
            citations       = citations,
            model_used      = llm.model,
            n_chunks_used   = len(chunks),
            retrieval_trace = retrieval_trace if trace else None,
        )

    # ── lazy loaders ──────────────────────────────────────────────────────────

    def _get_retriever(self) -> HybridRetriever:
        if self._retriever is None:
            cfg = self.config
            retriever_cfg = RetrieverConfig(
                top_k=cfg.top_k,
                allowed_tickers=cfg.allowed_tickers,
                **{k: v for k, v in vars(cfg.retriever_config).items()
                   if k not in ("top_k", "allowed_tickers")},
            )
            self._retriever = HybridRetriever(retriever_cfg)
        return self._retriever

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.config)
        return self._llm

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = load_system_prompt()
        return self._system_prompt


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Answer a question over SEC EDGAR filings"
    )
    parser.add_argument("question", help="Natural-language question")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            f"LLM to use (default: {DEFAULT_MODEL}). "
            "Prefix with 'ollama:' for local models, e.g. ollama:llama3.2"
        ),
    )
    parser.add_argument(
        "--top-k", type=int, default=15,
        help="Number of chunks to retrieve (default: 15)",
    )
    parser.add_argument(
        "--trace", action="store_true",
        help="Print retrieval routing and candidate counts",
    )
    args = parser.parse_args()

    config = AnswerConfig(
        model            = args.model,
        top_k            = args.top_k,
        retriever_config = RetrieverConfig(top_k=args.top_k),
    )
    engine = AnswerEngine(config)

    result = (
        engine.answer_with_trace(args.question)
        if args.trace
        else engine.answer(args.question)
    )

    if args.trace and result.retrieval_trace:
        r = result.retrieval_trace.route
        print("\n── Retrieval ─────────────────────────────────────────────")
        print(f"  Tickers    : {r.tickers or '(all)'}")
        print(f"  Sections   : {r.sections}")
        print(f"  Date from  : {r.date_from or '(none)'}")
        print(f"  Filing     : {r.filing_type or '(any)'}")
        print(f"  Candidates : {result.retrieval_trace.n_candidates}")
        print(f"  Chunks used: {result.n_chunks_used}")

    print(f"\n── Answer  [{result.model_used}] {'─' * 40}")
    print(result.answer_text)

    if result.citations:
        print("\n── Sources ───────────────────────────────────────────────")
        for c in result.citations:
            print(
                f"  [{c.index}] {c.ticker} · {c.filing_type} · "
                f"{c.filing_date} · {c.section_id}"
            )
            print(f"       {CORPUS_DIR / c.source_file}")


if __name__ == "__main__":
    main()
