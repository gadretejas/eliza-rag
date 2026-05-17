"""
Role-based permission definitions.

Enforces:
  - Which LLM models each role can use
  - Rate limits per role (requests / hour)
  - Corpus access is handled via allowed_tickers in JWT claims
"""

from __future__ import annotations

from fastapi import HTTPException

from api.auth import TokenClaims

# ── Model access ──────────────────────────────────────────────────────────────

# "*" means unrestricted; otherwise an explicit allowlist.
_ALLOWED_MODELS: dict[str, set[str] | str] = {
    "admin":   "*",
    "analyst": "*",
    "viewer":  {"gpt-5.4-mini", "claude-haiku-4-5"},
}


def check_model_access(claims: TokenClaims, model: str) -> None:
    """Raise 403 if the user's role cannot use the requested model."""
    allowed = _ALLOWED_MODELS.get(claims.role, set())
    if allowed == "*":
        return
    if model not in allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Role '{claims.role}' cannot use model '{model}'. "
                f"Allowed: {sorted(allowed)}"
            ),
        )


# ── Corpus access ─────────────────────────────────────────────────────────────

def get_ticker_filter(claims: TokenClaims) -> list[str] | None:
    """
    Return the list of tickers the user may query, or None for unrestricted.
    This is passed into AnswerConfig.allowed_tickers → RetrieverConfig.
    """
    return claims.tickers_list() if hasattr(claims, "tickers_list") else _parse_tickers(claims.allowed_tickers)


def _parse_tickers(raw: str) -> list[str] | None:
    if raw == "*":
        return None
    import json
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── Rate limiting (simple in-memory, per-process) ────────────────────────────
# For production replace with Redis or a proper rate-limiter middleware.

import time
from collections import defaultdict

_RATE_LIMITS: dict[str, int | None] = {  # requests per hour; None = unlimited
    "admin":   None,
    "analyst": 200,
    "viewer":  20,
}

_request_log: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(claims: TokenClaims) -> None:
    """Raise 429 if the user has exceeded their hourly request quota."""
    limit = _RATE_LIMITS.get(claims.role)
    if limit is None:
        return

    now    = time.time()
    window = now - 3600  # 1-hour sliding window
    key    = f"{claims.user_id}"
    log    = _request_log[key]

    # Prune entries outside the window
    _request_log[key] = [t for t in log if t > window]

    if len(_request_log[key]) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({limit} requests/hour for role '{claims.role}')",
        )

    _request_log[key].append(now)
