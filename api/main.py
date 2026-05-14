#!/usr/bin/env python3
"""
FastAPI backend for the SEC EDGAR RAG system.

Usage:
    uvicorn api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.answer.answer import AnswerEngine, AnswerConfig

app = FastAPI(title="SEC EDGAR RAG API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_engine: AnswerEngine | None = None


def _get_engine() -> AnswerEngine:
    global _engine
    if _engine is None:
        _engine = AnswerEngine(AnswerConfig())
    return _engine


class AskRequest(BaseModel):
    question: str
    model: str = "gpt-5.4-mini"
    top_k: int = 15


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]


@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    config = AnswerConfig(model=req.model, top_k=req.top_k)
    engine = AnswerEngine(config)
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
