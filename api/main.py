#!/usr/bin/env python3
"""
FastAPI backend for the SEC EDGAR RAG system.

Usage:
    uvicorn api.main:app --reload
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.answer.answer import AnswerConfig, AnswerEngine
from api.auth import TokenClaims, get_current_user, router as auth_router
from api.permissions import check_model_access, check_rate_limit, get_ticker_filter
from api.users import init_db
from api.history import (
    init_history_db, save_conversation, router as history_router,
)
from api.sessions import init_sessions_db, router as sessions_router
from api.document import router as document_router

# ── Bootstrap ─────────────────────────────────────────────────────────────────

init_db()           # creates users table and seeds default admin on first boot
init_history_db()   # creates conversations table
init_sessions_db()  # creates sessions + session_messages tables

app = FastAPI(title="SEC EDGAR RAG API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

# ── Admin routes (user management) ────────────────────────────────────────────

from fastapi import APIRouter
from api.auth import require_admin
from api.users import list_users, update_user, delete_user, User
from pydantic import BaseModel as _BM

admin_router = APIRouter(prefix="/admin", tags=["admin"])

class UpdateUserRequest(_BM):
    role:            str | None = None
    allowed_tickers: str | None = None
    is_active:       bool | None = None

@admin_router.get("/users")
def admin_list_users(_: TokenClaims = Depends(require_admin)) -> list[dict]:
    return [
        {
            "id":              u.id,
            "email":           u.email,
            "role":            u.role,
            "allowed_tickers": u.allowed_tickers,
            "is_active":       u.is_active,
            "created_at":      u.created_at,
        }
        for u in list_users()
    ]

@admin_router.patch("/users/{user_id}")
def admin_update_user(
    user_id: int,
    req: UpdateUserRequest,
    _: TokenClaims = Depends(require_admin),
) -> dict:
    update_user(
        user_id,
        role=req.role,
        allowed_tickers=req.allowed_tickers,
        is_active=req.is_active,
    )
    return {"ok": True}

@admin_router.delete("/users/{user_id}")
def admin_delete_user(
    user_id: int,
    _: TokenClaims = Depends(require_admin),
) -> dict:
    delete_user(user_id)
    return {"ok": True}

app.include_router(admin_router)
app.include_router(history_router)
app.include_router(sessions_router)
app.include_router(document_router)

# ── Request / response schemas ─────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    model:    str = "gpt-5.4-mini"
    top_k:    int = 15
    provider: Literal["openai", "anthropic", "local"] | None = None
    api_key:  str | None = None
    base_url: str | None = None


class AskResponse(BaseModel):
    answer:  str
    sources: list[dict]


# ── Engine cache ───────────────────────────────────────────────────────────────
# Keyed by (provider, model, top_k, ticker_hash) so users with different corpus
# restrictions never share a cached engine.

import hashlib

_engines: dict[str, AnswerEngine] = {}


def _ticker_hash(tickers: list[str] | None) -> str:
    if tickers is None:
        return "all"
    return hashlib.md5(",".join(sorted(tickers)).encode()).hexdigest()[:8]


def _get_engine(req: AskRequest, ticker_filter: list[str] | None) -> AnswerEngine:
    if req.api_key:
        # Never cache user-supplied keys
        return AnswerEngine(AnswerConfig(
            model=req.model, top_k=req.top_k,
            provider=req.provider, api_key=req.api_key, base_url=req.base_url,
            allowed_tickers=ticker_filter,
        ))
    key = f"{req.provider or 'openai'}:{req.model}:{req.top_k}:{_ticker_hash(ticker_filter)}"
    if key not in _engines:
        _engines[key] = AnswerEngine(AnswerConfig(
            model=req.model, top_k=req.top_k,
            provider=req.provider, base_url=req.base_url,
            allowed_tickers=ticker_filter,
        ))
    return _engines[key]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/api/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    user: TokenClaims = Depends(get_current_user),
) -> AskResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    check_model_access(user, req.model)
    check_rate_limit(user)

    ticker_filter = get_ticker_filter(user)
    engine = _get_engine(req, ticker_filter)
    result = engine.answer(req.question)

    sources = [
        {
            "index":       c.index,
            "ticker":      c.ticker,
            "filing_type": c.filing_type,
            "filing_date": c.filing_date,
            "section":     c.section_id,
            "snippet":     c.passage_text[:400],
        }
        for c in result.citations
    ]

    # ── Save to history ────────────────────────────────────────────────────────
    if result.answer_text:
        save_conversation(
            user_id  = user.user_id,
            title    = req.question[:60].rstrip(),
            question = req.question,
            answer   = result.answer_text,
            model    = req.model,
            sources  = json.dumps(sources),
        )

    return AskResponse(answer=result.answer_text, sources=sources)


_stream_executor = ThreadPoolExecutor(max_workers=4)


@app.post("/api/ask/stream")
async def ask_stream(
    req: AskRequest,
    user: TokenClaims = Depends(get_current_user),
) -> StreamingResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    check_model_access(user, req.model)
    check_rate_limit(user)

    ticker_filter = get_ticker_filter(user)
    engine = _get_engine(req, ticker_filter)

    async def generate():
        loop  = asyncio.get_event_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        accumulated_text:    list[str]  = []
        accumulated_sources: list[dict] = []

        def run_sync():
            try:
                for event in engine.answer_stream(req.question):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "detail": str(e)}
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(_stream_executor, run_sync)

        while True:
            event = await queue.get()
            if event is None:
                break
            if event["type"] == "chunk":
                accumulated_text.append(event.get("text", ""))
            elif event["type"] == "sources":
                accumulated_sources = event.get("sources", [])
            elif event["type"] == "done":
                # ── Save before emitting done so frontend receives saved first ──
                answer_text = "".join(accumulated_text)
                if answer_text:
                    conv_id = save_conversation(
                        user_id  = user.user_id,
                        title    = req.question[:60].rstrip(),
                        question = req.question,
                        answer   = answer_text,
                        model    = req.model,
                        sources  = json.dumps(accumulated_sources),
                    )
                    yield f"data: {json.dumps({'type': 'saved', 'conv_id': conv_id})}\n\n"
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
