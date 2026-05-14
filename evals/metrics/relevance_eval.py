"""
Tier 4 — Answer relevance.

Uses an LLM-as-judge to rate how well the generated answer addresses
the original question, on a scale of 1–5.

Usage:
    from evals.metrics.relevance_eval import evaluate_relevance
    result = evaluate_relevance(question, answer, llm_client)
"""

from __future__ import annotations

import json
import sys
import time


_SYSTEM_PROMPT = """\
You are an expert evaluator assessing the quality of AI-generated answers to \
financial research questions about SEC filings.

Rate how well the answer addresses the question on a scale of 1 to 5:
  5 — Fully answers the question with accurate, specific details
  4 — Mostly answers the question; minor gaps or vague areas
  3 — Partially answers; addresses some aspects but misses key points
  2 — Barely answers; mostly off-topic or too generic
  1 — Completely fails to address the question

Return ONLY a JSON object: {"score": <int 1-5>, "reason": "<one sentence>"}
Do not include any text outside the JSON object."""

_USER_TEMPLATE = """\
Question: {question}

Answer:
{answer}"""


def evaluate_relevance(
    question: str,
    answer: str,
    llm_client,
    max_retries: int = 2,
) -> dict:
    """
    Ask an LLM judge to rate how relevant the answer is to the question.

    Returns dict with: score (1–5 int), reason (str).
    """
    if not answer.strip():
        return {"score": 1, "reason": "Empty answer"}

    user_msg = _USER_TEMPLATE.format(question=question, answer=answer)

    for attempt in range(max_retries + 1):
        try:
            raw = llm_client.complete(
                system=_SYSTEM_PROMPT,
                user=user_msg,
                temperature=0,
                max_tokens=128,
            )
            result = json.loads(raw.strip())
            score  = int(result.get("score", 1))
            score  = max(1, min(5, score))  # clamp to [1, 5]
            return {
                "score":  score,
                "reason": str(result.get("reason", "")),
            }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Sometimes the model wraps JSON in markdown fences
            raw_stripped = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            try:
                result = json.loads(raw_stripped)
                return {
                    "score":  max(1, min(5, int(result.get("score", 1)))),
                    "reason": str(result.get("reason", "")),
                }
            except Exception:
                pass
            if attempt < max_retries:
                time.sleep(1)
                continue
            print(f"  Warning: relevance judge parse error: {e}", file=sys.stderr)
            return {"score": 1, "reason": f"Parse error: {e}"}
        except Exception as e:
            print(f"  Warning: relevance judge call failed: {e}", file=sys.stderr)
            return {"score": 1, "reason": f"Call failed: {e}"}


def run_tier4(examples: list[dict], llm_client) -> list[dict]:
    """
    Evaluate all examples with Tier 4 relevance.

    Each example dict must have:
        id: str
        question: str
        generated_answer: str
    """
    results = []
    for ex in examples:
        r = {"id": ex["id"]}
        rel = evaluate_relevance(ex["question"], ex["generated_answer"], llm_client)
        r["relevance_score"]  = rel["score"]
        r["relevance_reason"] = rel["reason"]
        results.append(r)
    return results


def aggregate_tier4(results: list[dict]) -> dict[str, float]:
    if not results:
        return {}
    return {
        "relevance_score": round(
            sum(r["relevance_score"] for r in results) / len(results), 4
        ),
    }
