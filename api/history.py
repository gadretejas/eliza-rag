"""
Conversation history store — SQLite-backed CRUD.

Schema
------
conversations (id, user_id, title, question, answer, model, sources, created_at)

sources is stored as a JSON string: list of source objects matching the /api/ask
response shape.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import TokenClaims, get_current_user
from api.users import DB_PATH


# ── Schema ────────────────────────────────────────────────────────────────────

def init_history_db() -> None:
    """Create conversations table if it doesn't exist."""
    from api.users import _conn
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title      TEXT    NOT NULL,
                question   TEXT    NOT NULL,
                answer     TEXT    NOT NULL,
                model      TEXT    NOT NULL,
                sources    TEXT    NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_user_created
                ON conversations(user_id, created_at DESC)
        """)


# ── Data access ───────────────────────────────────────────────────────────────

@dataclass
class ConversationRow:
    id:         int
    user_id:    int
    title:      str
    question:   str
    answer:     str
    model:      str
    sources:    str          # raw JSON string
    created_at: str


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_conv(row: sqlite3.Row) -> ConversationRow:
    return ConversationRow(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        question=row["question"],
        answer=row["answer"],
        model=row["model"],
        sources=row["sources"],
        created_at=row["created_at"],
    )


def save_conversation(
    user_id:  int,
    title:    str,
    question: str,
    answer:   str,
    model:    str,
    sources:  str,          # JSON string
) -> int:
    """Insert a new conversation row and return its id."""
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO conversations (user_id, title, question, answer, model, sources)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, title, question, answer, model, sources),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_conversations(
    user_id: int,
    limit:   int = 20,
    offset:  int = 0,
) -> tuple[list[ConversationRow], int]:
    """Return (rows, total_count) for a user, newest first."""
    with _conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT * FROM conversations
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ).fetchall()
    return [_row_to_conv(r) for r in rows], total


def get_recent_conversations(user_id: int, limit: int = 5) -> list[ConversationRow]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM conversations
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [_row_to_conv(r) for r in rows]


def get_conversation(conv_id: int, user_id: int) -> ConversationRow | None:
    """Return conversation only if it belongs to user_id."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
    return _row_to_conv(row) if row else None


def delete_conversation(conv_id: int, user_id: int) -> bool:
    """Delete conversation if owned by user_id. Returns True if deleted."""
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        )
    return cur.rowcount > 0


# ── API Router ────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/history", tags=["history"])


class ConversationSummaryOut(BaseModel):
    id:         int
    title:      str
    model:      str
    created_at: str


class ConversationDetailOut(ConversationSummaryOut):
    question: str
    answer:   str
    sources:  list[dict]


class HistoryListOut(BaseModel):
    items: list[ConversationSummaryOut]
    total: int


def _to_summary(row: ConversationRow) -> ConversationSummaryOut:
    return ConversationSummaryOut(
        id=row.id,
        title=row.title,
        model=row.model,
        created_at=row.created_at,
    )


@router.get("", response_model=HistoryListOut)
def list_history(
    limit:  int = 20,
    offset: int = 0,
    user:   TokenClaims = Depends(get_current_user),
) -> HistoryListOut:
    limit  = max(1, min(limit, 100))
    rows, total = get_conversations(user.user_id, limit=limit, offset=offset)
    return HistoryListOut(items=[_to_summary(r) for r in rows], total=total)


@router.get("/recent", response_model=HistoryListOut)
def list_recent(
    user: TokenClaims = Depends(get_current_user),
) -> HistoryListOut:
    rows = get_recent_conversations(user.user_id, limit=5)
    return HistoryListOut(items=[_to_summary(r) for r in rows], total=len(rows))


@router.get("/{conv_id}", response_model=ConversationDetailOut)
def get_history_item(
    conv_id: int,
    user:    TokenClaims = Depends(get_current_user),
) -> ConversationDetailOut:
    row = get_conversation(conv_id, user.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetailOut(
        id=row.id,
        title=row.title,
        model=row.model,
        created_at=row.created_at,
        question=row.question,
        answer=row.answer,
        sources=json.loads(row.sources),
    )


@router.delete("/{conv_id}")
def delete_history_item(
    conv_id: int,
    user:    TokenClaims = Depends(get_current_user),
) -> dict:
    deleted = delete_conversation(conv_id, user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}
