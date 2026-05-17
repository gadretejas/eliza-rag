"""
Chat session store — multi-turn follow-up conversations.

Tables
------
sessions         (id, user_id, title, model, created_at)
session_messages (id, session_id, role, content, sources, tokens, created_at)
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import TokenClaims, get_current_user
from api.history import get_conversation
from api.permissions import check_model_access, check_rate_limit, get_ticker_filter
from api.token_count import count_messages_tokens, get_context_limit
from api.users import DB_PATH


# ── Schema ─────────────────────────────────────────────────────────────────────

def init_sessions_db() -> None:
    from api.users import _conn
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title      TEXT    NOT NULL,
                model      TEXT    NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role       TEXT    NOT NULL CHECK(role IN ('user','assistant')),
                content    TEXT    NOT NULL,
                sources    TEXT    NOT NULL DEFAULT '[]',
                tokens     INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sess_user
                ON sessions(user_id, created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sess_msg
                ON session_messages(session_id, created_at ASC)
        """)


# ── Data access ────────────────────────────────────────────────────────────────

@dataclass
class SessionRow:
    id:         int
    user_id:    int
    title:      str
    model:      str
    created_at: str


@dataclass
class MessageRow:
    id:         int
    session_id: int
    role:       str
    content:    str
    sources:    str   # raw JSON
    tokens:     int
    created_at: str


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_session(r: sqlite3.Row) -> SessionRow:
    return SessionRow(id=r["id"], user_id=r["user_id"], title=r["title"],
                      model=r["model"], created_at=r["created_at"])


def _row_to_msg(r: sqlite3.Row) -> MessageRow:
    return MessageRow(id=r["id"], session_id=r["session_id"], role=r["role"],
                      content=r["content"], sources=r["sources"],
                      tokens=r["tokens"], created_at=r["created_at"])


def create_session(user_id: int, title: str, model: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (user_id, title, model) VALUES (?,?,?)",
            (user_id, title, model),
        )
        return cur.lastrowid  # type: ignore[return-value]


def append_message(
    session_id: int, role: str, content: str,
    sources: str = "[]", tokens: int = 0,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO session_messages (session_id, role, content, sources, tokens)
               VALUES (?,?,?,?,?)""",
            (session_id, role, content, sources, tokens),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_session(session_id: int, user_id: int) -> SessionRow | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)
        ).fetchone()
    return _row_to_session(row) if row else None


def get_messages(session_id: int) -> list[MessageRow]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM session_messages WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    return [_row_to_msg(r) for r in rows]


def list_sessions(
    user_id: int, limit: int = 20, offset: int = 0
) -> tuple[list[SessionRow], int]:
    with _conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
    return [_row_to_session(r) for r in rows], total


def count_session_tokens(session_id: int) -> int:
    with _conn() as conn:
        val = conn.execute(
            "SELECT COALESCE(SUM(tokens),0) FROM session_messages WHERE session_id=?",
            (session_id,),
        ).fetchone()[0]
    return int(val)


def delete_session(session_id: int, user_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)
        )
    return cur.rowcount > 0


# ── API Router ─────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_executor = ThreadPoolExecutor(max_workers=4)


# ── Pydantic models ────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    conv_id: int | None = None   # seed from existing single-turn Q&A
    model:   str        = "gpt-5.4-mini"


class SendMessageRequest(BaseModel):
    question: str
    top_k:    int = 15
    provider: Literal["openai", "anthropic", "local"] | None = None
    api_key:  str | None = None
    base_url: str | None = None


class MessageOut(BaseModel):
    id:         int
    role:       str
    content:    str
    sources:    list[dict]
    tokens:     int
    created_at: str


class SessionDetailOut(BaseModel):
    id:            int
    title:         str
    model:         str
    created_at:    str
    messages:      list[MessageOut]
    tokens_used:   int
    context_limit: int


class SessionSummaryOut(BaseModel):
    id:         int
    title:      str
    model:      str
    created_at: str


class SessionListOut(BaseModel):
    items: list[SessionSummaryOut]
    total: int


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("", response_model=dict)
def create_session_endpoint(
    req: CreateSessionRequest,
    user: TokenClaims = Depends(get_current_user),
) -> dict:
    """Create a new session, optionally seeding it from a single-turn conversation."""
    model = req.model
    title = "New chat"
    session_id = create_session(user.user_id, title, model)

    if req.conv_id is not None:
        conv = get_conversation(req.conv_id, user.user_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        title = conv.title
        # Seed first two messages from the single-turn Q&A
        from api.token_count import count_tokens
        u_tokens = count_tokens(conv.question, model)
        a_tokens = count_tokens(conv.answer, model)
        append_message(session_id, "user",      conv.question, "[]",        u_tokens)
        append_message(session_id, "assistant", conv.answer,   conv.sources, a_tokens)
        # Update title
        with _conn() as conn:
            conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, session_id))

    context_limit = get_context_limit(model)
    return {"session_id": session_id, "context_limit": context_limit}


@router.get("", response_model=SessionListOut)
def list_sessions_endpoint(
    limit:  int = 20,
    offset: int = 0,
    user:   TokenClaims = Depends(get_current_user),
) -> SessionListOut:
    rows, total = list_sessions(user.user_id, limit=max(1, min(limit, 100)), offset=offset)
    return SessionListOut(
        items=[SessionSummaryOut(id=r.id, title=r.title, model=r.model, created_at=r.created_at)
               for r in rows],
        total=total,
    )


@router.get("/{session_id}", response_model=SessionDetailOut)
def get_session_endpoint(
    session_id: int,
    user: TokenClaims = Depends(get_current_user),
) -> SessionDetailOut:
    session = get_session(session_id, user.user_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    msgs = get_messages(session_id)
    tokens_used = sum(m.tokens for m in msgs)
    context_limit = get_context_limit(session.model)
    return SessionDetailOut(
        id=session.id,
        title=session.title,
        model=session.model,
        created_at=session.created_at,
        messages=[
            MessageOut(
                id=m.id, role=m.role, content=m.content,
                sources=json.loads(m.sources), tokens=m.tokens,
                created_at=m.created_at,
            )
            for m in msgs
        ],
        tokens_used=tokens_used,
        context_limit=context_limit,
    )


@router.delete("/{session_id}")
def delete_session_endpoint(
    session_id: int,
    user: TokenClaims = Depends(get_current_user),
) -> dict:
    if not delete_session(session_id, user.user_id):
        raise HTTPException(404, "Session not found")
    return {"ok": True}


@router.post("/{session_id}/message")
async def send_message(
    session_id: int,
    req:        SendMessageRequest,
    user:       TokenClaims = Depends(get_current_user),
) -> StreamingResponse:
    if not req.question.strip():
        raise HTTPException(400, "question must not be empty")

    session = get_session(session_id, user.user_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    check_model_access(user, session.model)
    check_rate_limit(user)

    context_limit = get_context_limit(session.model)
    tokens_so_far = count_session_tokens(session_id)

    if tokens_so_far >= context_limit:
        raise HTTPException(422, "Context limit reached. Start a new chat.")

    # Load conversation history for the LLM
    msgs = get_messages(session_id)
    history = [{"role": m.role, "content": m.content} for m in msgs]

    # Build engine
    from src.answer.answer import AnswerConfig, AnswerEngine
    ticker_filter = get_ticker_filter(user)
    engine_cfg = AnswerConfig(
        model=session.model,
        top_k=req.top_k,
        provider=req.provider,
        api_key=req.api_key,
        base_url=req.base_url,
        allowed_tickers=ticker_filter,
    )
    engine = AnswerEngine(engine_cfg)

    async def generate():
        loop  = asyncio.get_event_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        accumulated_text:    list[str]  = []
        accumulated_sources: list[dict] = []
        final_tokens_used: list[int]    = [tokens_so_far]

        def run_sync():
            try:
                for event in engine.followup_stream(
                    history, req.question,
                    tokens_so_far=tokens_so_far,
                    context_limit=context_limit,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "detail": str(e)}
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(_executor, run_sync)

        while True:
            event = await queue.get()
            if event is None:
                # Save user message + assistant reply to DB
                from api.token_count import count_tokens
                from api.token_usage import log_token_usage
                q_tokens = count_tokens(req.question, session.model)
                answer_text = "".join(accumulated_text)
                a_tokens    = count_tokens(answer_text, session.model)
                append_message(session_id, "user",      req.question, "[]", q_tokens)
                append_message(session_id, "assistant", answer_text,
                               json.dumps(accumulated_sources), a_tokens)
                # Log token usage for the admin dashboard
                log_token_usage(
                    user_id           = user.user_id,
                    user_email        = user.email,
                    model             = session.model,
                    endpoint          = "session/message",
                    prompt_tokens     = q_tokens,
                    completion_tokens = a_tokens,
                )
                break
            if event["type"] == "chunk":
                accumulated_text.append(event.get("text", ""))
            elif event["type"] == "sources":
                accumulated_sources = event.get("sources", [])
            elif event["type"] == "token_count":
                final_tokens_used[0] = event.get("tokens_used", tokens_so_far)
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
