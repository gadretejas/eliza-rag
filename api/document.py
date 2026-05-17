"""
Document viewer endpoint — serves the full filing text from the corpus.

GET /api/document
  ?ticker=AAPL
  &filing_type=10-K
  &filing_date=2024-11-01
  &section=Item+1A      ← used only for header metadata, not to filter the text
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import TokenClaims, get_current_user
from src.config import CORPUS_DIR
from src.pipeline.chunk import extract_body, strip_toc, split_into_sections


router = APIRouter(prefix="/api/document", tags=["document"])


# ── Corpus file lookup ─────────────────────────────────────────────────────────

def _normalise_type(filing_type: str) -> str:
    """'10-K (Annual Report)' → '10K', '10-Q' → '10Q'"""
    return filing_type.split()[0].replace("-", "")


def find_corpus_file(ticker: str, filing_type: str, filing_date: str) -> Path | None:
    """Return the corpus .txt file matching (ticker, filing_type, filing_date)."""
    norm = _normalise_type(filing_type)
    for path in sorted(CORPUS_DIR.iterdir()):
        name = path.name
        if (
            name.endswith("_full.txt")
            and ticker.upper() in name
            and norm in name
            and filing_date in name
        ):
            return path
    return None


def _norm_id(s: str) -> str:
    """Normalise section id for comparison: 'Item 1A.' → 'item1a'"""
    return s.strip().rstrip(".").lower().replace(" ", "")


def get_full_document(
    ticker:      str,
    filing_type: str,
    filing_date: str,
    section_id:  str,          # e.g. "Item 1A" — used only for metadata lookup
) -> tuple[str, str, str]:     # (resolved_section_id, section_name, full_body_text)
    """
    Return the full body text of the filing plus the resolved section id/name.
    Raises FileNotFoundError when no corpus file is found.
    """
    path = find_corpus_file(ticker, filing_type, filing_date)
    if path is None:
        raise FileNotFoundError(
            f"No corpus file found for {ticker} {filing_type} {filing_date}"
        )

    raw  = path.read_text(encoding="utf-8", errors="replace")

    # Use the same body extraction as the chunking pipeline:
    # skip XBRL preamble, then remove Table of Contents entries
    body = strip_toc(extract_body(raw))

    # Resolve section metadata (id + name) for the panel header — don't filter text
    target = _norm_id(section_id)
    resolved_id   = section_id
    resolved_name = section_id
    for sid, sname, _ in split_into_sections(body):
        if _norm_id(sid) == target:
            resolved_id   = sid
            resolved_name = sname
            break

    return resolved_id, resolved_name, body


# ── Response model ─────────────────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    ticker:       str
    filing_type:  str
    filing_date:  str
    section_id:   str
    section_name: str
    text:         str


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("", response_model=DocumentResponse)
def get_document(
    ticker:      str,
    filing_type: str,
    filing_date: str,
    section:     str,
    _user:       TokenClaims = Depends(get_current_user),
) -> DocumentResponse:
    """
    Return the full text of a corpus filing (XBRL preamble and ToC stripped).
    The `section` parameter is used only to resolve section metadata for the
    panel header — the entire document body is always returned as `text`.
    """
    try:
        sid, sname, text = get_full_document(ticker, filing_type, filing_date, section)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return DocumentResponse(
        ticker=ticker.upper(),
        filing_type=filing_type.split()[0],
        filing_date=filing_date,
        section_id=sid,
        section_name=sname,
        text=text,
    )
