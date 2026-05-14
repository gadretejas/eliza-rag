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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.answer.answer import AnswerEngine, AnswerConfig

app = FastAPI(title="SEC EDGAR RAG API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from typing import Literal

class AskRequest(BaseModel):
    question: str
    model: str = "gpt-5.4-mini"
    top_k: int = 15
    provider: Literal["openai", "anthropic", "local"] | None = None
    api_key: str | None = None
    base_url: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]


# Singleton engine — ChromaDB is opened once at first request and reused.
# Custom-keyed requests (user-supplied api_key) are never cached.
_engines: dict[str, AnswerEngine] = {}


def _get_engine(req: AskRequest) -> AnswerEngine:
    if req.api_key:
        # Never cache user-supplied keys
        return AnswerEngine(AnswerConfig(
            model=req.model, top_k=req.top_k,
            provider=req.provider, api_key=req.api_key, base_url=req.base_url,
        ))
    key = f"{req.provider or 'openai'}:{req.model}:{req.top_k}"
    if key not in _engines:
        _engines[key] = AnswerEngine(AnswerConfig(
            model=req.model, top_k=req.top_k,
            provider=req.provider, base_url=req.base_url,
        ))
    return _engines[key]


@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    engine = _get_engine(req)
    result = engine.answer(req.question)

    sources = [
        {
            "index": c.index,
            "ticker": c.ticker,
            "filing_type": c.filing_type,
            "filing_date": c.filing_date,
            "section": c.section_id,
            "snippet": c.passage_text[:400],
        }
        for c in result.citations
    ]

    return AskResponse(answer=result.answer_text, sources=sources)


_stream_executor = ThreadPoolExecutor(max_workers=4)


@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    engine = _get_engine(req)

    async def generate():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

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
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
