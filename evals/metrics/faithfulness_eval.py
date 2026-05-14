"""
Tier 3 — Faithfulness (no hallucination).

Uses an LLM-as-judge to check that every factual claim in the generated
answer is supported by the retrieved context chunks.

Usage:
    from evals.metrics.faithfulness_eval import evaluate_faithfulness
    result = evaluate_faithfulness(answer, chunks, llm_client)
"""

from __future__ import annotations

import json
import sys
import time


_SYSTEM_PROMPT = """\
You are a precise fact-checker evaluating whether an AI-generated answer is \
grounded in the provided source documents.

Given a context (one or more document excerpts) and an answer, your task is:
1. Identify every distinct factual claim made in the answer.
2. For each claim, determine whether it is DIRECTLY supported by the context.
   - "Directly supported" means the context contains information that confirms
     the claim without requiring external knowledge.
   - Paraphrases and synonyms count as supported.
   - Claims that are plausible but not mentioned in the context count as
     UNSUPPORTED.
3. Return ONLY valid JSON in this exact format:
   {"supported": <int>, "unsupported": <int>, "score": <float>, "unsupported_claims": [<str>, ...]}
   where score = supported / (supported + unsupported), rounded to 2 decimal places.
   If the answer contains no factual claims, return {"supported": 0, "unsupported": 0, "score": 1.0, "unsupported_claims": []}.
Do not include any text outside the JSON object."""

_USER_TEMPLATE = """\
CONTEXT:
{context}

ANSWER:
{answer}"""


def _chunks_to_context(chunks: list[dict], max_chars: int = 8000) -> str:
    """Format retrieved chunks into a single context string for the judge."""
    lines = []
    total = 0
    for i, c in enumerate(chunks, start=1):
        header = f"[{i}] {c.get('ticker','?')} · {c.get('filing_type','?')} · {c.get('filing_date','?')}"
        text   = c.get("text", c.get("snippet", ""))[:1000]
        block  = f"{header}\n{text}"
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block)
    return "\n\n".join(lines)


def evaluate_faithfulness(
    answer: str,
    chunks: list[dict],
    llm_client,
    max_retries: int = 2,
) -> dict:
    """
    Ask an LLM judge to rate how faithfully the answer is grounded in chunks.

    llm_client — an LLMClient instance (from src.answer.answer) or any object
                 with a .complete(system, user) -> str method.

    Returns dict with: score (0–1), supported (int), unsupported (int),
                       unsupported_claims (list[str]).
    """
    if not answer.strip():
        return {"score": 1.0, "supported": 0, "unsupported": 0, "unsupported_claims": []}

    context  = _chunks_to_context(chunks)
    user_msg = _USER_TEMPLATE.format(context=context, answer=answer)

    for attempt in range(max_retries + 1):
        try:
            raw = llm_client.complete(
                system=_SYSTEM_PROMPT,
                user=user_msg,
                temperature=0,
                max_tokens=512,
            )
            result = json.loads(raw.strip())
            # Validate expected keys
            score = float(result.get("score", 0.0))
            return {
                "score":             round(score, 4),
                "supported":         int(result.get("supported", 0)),
                "unsupported":       int(result.get("unsupported", 0)),
                "unsupported_claims": result.get("unsupported_claims", []),
            }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            if attempt < max_retries:
                time.sleep(1)
                continue
            print(f"  Warning: faithfulness judge parse error: {e}", file=sys.stderr)
            return {"score": 0.0, "supported": 0, "unsupported": 0, "unsupported_claims": []}
        except Exception as e:
            print(f"  Warning: faithfulness judge call failed: {e}", file=sys.stderr)
            return {"score": 0.0, "supported": 0, "unsupported": 0, "unsupported_claims": []}


def run_tier3(examples: list[dict], llm_client) -> list[dict]:
    """
    Evaluate all examples with Tier 3 faithfulness.

    Each example dict must have:
        id: str
        generated_answer: str
        retrieved_chunks: list[dict]
    """
    results = []
    for ex in examples:
        r = {"id": ex["id"]}
        faith = evaluate_faithfulness(
            ex["generated_answer"],
            ex["retrieved_chunks"],
            llm_client,
        )
        r["faithfulness_score"]      = faith["score"]
        r["supported_claims"]        = faith["supported"]
        r["unsupported_claims"]      = faith["unsupported"]
        r["unsupported_claims_list"] = faith["unsupported_claims"]
        results.append(r)
    return results


def aggregate_tier3(results: list[dict]) -> dict[str, float]:
    if not results:
        return {}
    return {
        "faithfulness_score": round(
            sum(r["faithfulness_score"] for r in results) / len(results), 4
        ),
        "avg_unsupported_claims": round(
            sum(r["unsupported_claims"] for r in results) / len(results), 2
        ),
    }
