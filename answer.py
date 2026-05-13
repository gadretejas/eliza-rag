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
from dataclasses import dataclass, field
from pathlib import Path

from retrieve import HybridRetriever, RetrieverConfig, RetrievalTrace

PROMPTS_DIR        = Path(__file__).parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.md"
CORPUS_DIR         = Path("edgar_corpus")

DEFAULT_MODEL    = "gpt-5.4-mini"
OLLAMA_BASE_URL  = "http://localhost:11434/v1"
OPENAI_BASE_URL  = "https://api.openai.com/v1"
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
    Wraps openai.OpenAI. Routes to Ollama (local) or OpenAI based on the
    model string prefix and environment.

    Model routing:
        "ollama:<name>"   → Ollama at localhost:11434
        any other string  → OpenAI (requires OPENAI_API_KEY); falls back to
                            Ollama if the key is absent
    """

    def __init__(self, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("openai not installed — run: pip install openai")

        if model.startswith("ollama:"):
            self.model  = model[len("ollama:"):]
            self._client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
            self._backend = "ollama"
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                print(
                    f"Warning: OPENAI_API_KEY not set — "
                    f"falling back to ollama:{OLLAMA_FALLBACK}",
                    file=sys.stderr,
                )
                self.model   = OLLAMA_FALLBACK
                self._client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
                self._backend = "ollama"
            else:
                self.model   = model
                self._client = OpenAI(api_key=api_key)
                self._backend = "openai"

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            sys.exit(f"LLM call failed ({self._backend}/{self.model}): {e}")


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
                **{k: v for k, v in vars(cfg.retriever_config).items() if k != "top_k"},
            )
            self._retriever = HybridRetriever(retriever_cfg)
        return self._retriever

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.config.model)
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
