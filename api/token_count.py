"""
Token counting helpers for context-window tracking.

Uses tiktoken for OpenAI-compatible models; falls back to a character-based
estimate (chars // 4) for Anthropic and local models.
"""

from __future__ import annotations

CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.4-mini":      128_000,
    "gpt-5.4":           128_000,
    "gpt-4o":            128_000,
    "gpt-4o-mini":       128_000,
    "claude-haiku-4-5":  200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-opus-4-5":   200_000,
}

DEFAULT_CONTEXT_WINDOW = 8_192   # safe fallback for unknown / custom models


def get_context_limit(model: str) -> int:
    """Return the context window (in tokens) for a model name."""
    return CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)


def count_tokens(text: str, model: str) -> int:
    """
    Count tokens in *text* for *model*.

    OpenAI models: uses tiktoken (accurate).
    Everything else: len(text) // 4  (rough but fast).
    """
    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(model)
            return len(enc.encode(text))
        except Exception:
            pass   # tiktoken not installed or unknown model — fall through
    return max(1, len(text) // 4)


def count_messages_tokens(
    messages: list[dict],
    model: str,
    system: str = "",
) -> int:
    """
    Estimate total tokens across a list of messages + optional system prompt.

    Each message dict must have a "content" key.
    Adds a small per-message overhead (4 tokens) matching the OpenAI cookbook.
    """
    overhead_per_message = 4
    total = count_tokens(system, model) if system else 0
    for msg in messages:
        total += count_tokens(msg.get("content", ""), model) + overhead_per_message
    return total
