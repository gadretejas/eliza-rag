"""
Token usage logging — records every LLM call so admins can see
consumption broken down by user and model.

Table: token_usage
"""

from __future__ import annotations

import sqlite3

from api.users import DB_PATH


# ── Schema ─────────────────────────────────────────────────────────────────────

def init_token_usage_db() -> None:
    from api.users import _conn
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           INTEGER NOT NULL,
                user_email        TEXT    NOT NULL,
                model             TEXT    NOT NULL,
                endpoint          TEXT    NOT NULL,
                prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens      INTEGER NOT NULL DEFAULT 0,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tu_user
                ON token_usage(user_id, created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tu_model
                ON token_usage(model, created_at DESC)
        """)


# ── Write ──────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_token_usage(
    user_id:           int,
    user_email:        str,
    model:             str,
    endpoint:          str,
    prompt_tokens:     int,
    completion_tokens: int,
) -> None:
    """Insert one token-usage record. Fire-and-forget; errors are silenced."""
    try:
        total = prompt_tokens + completion_tokens
        with _conn() as conn:
            conn.execute(
                """INSERT INTO token_usage
                       (user_id, user_email, model, endpoint,
                        prompt_tokens, completion_tokens, total_tokens)
                   VALUES (?,?,?,?,?,?,?)""",
                (user_id, user_email, model, endpoint,
                 prompt_tokens, completion_tokens, total),
            )
    except Exception:
        pass   # never let logging failures bubble up to the user


# ── Read ───────────────────────────────────────────────────────────────────────

def get_usage_stats() -> dict:
    """
    Return all-time token usage aggregated by user and model.

    Shape:
    {
      "users": [
        {
          "user_id":    1,
          "email":      "alice@example.com",
          "total":      862000,
          "by_model":   {"gpt-5.4-mini": 850000, "gpt-5.4": 12000},
          "call_count": 45,
        },
        ...
      ],
      "models":      ["gpt-5.4-mini", "gpt-5.4"],
      "grand_total": 1172000,
      "total_calls": 47,
    }
    """
    with _conn() as conn:
        # Per-user, per-model aggregates
        rows = conn.execute("""
            SELECT user_id, user_email, model,
                   SUM(total_tokens) AS tokens,
                   COUNT(*)          AS calls
            FROM   token_usage
            GROUP  BY user_id, model
            ORDER  BY user_id, model
        """).fetchall()

        grand_total = conn.execute(
            "SELECT COALESCE(SUM(total_tokens),0) FROM token_usage"
        ).fetchone()[0]

        total_calls = conn.execute(
            "SELECT COUNT(*) FROM token_usage"
        ).fetchone()[0]

    # Collect all distinct models (sorted)
    models: list[str] = sorted({r["model"] for r in rows})

    # Aggregate per user
    user_map: dict[int, dict] = {}
    for r in rows:
        uid = r["user_id"]
        if uid not in user_map:
            user_map[uid] = {
                "user_id":    uid,
                "email":      r["user_email"],
                "total":      0,
                "by_model":   {},
                "call_count": 0,
            }
        user_map[uid]["total"]                 += r["tokens"]
        user_map[uid]["by_model"][r["model"]]  = r["tokens"]
        user_map[uid]["call_count"]            += r["calls"]

    # Sort users by total tokens descending
    users = sorted(user_map.values(), key=lambda u: u["total"], reverse=True)

    return {
        "users":       users,
        "models":      models,
        "grand_total": int(grand_total),
        "total_calls": int(total_calls),
    }
