#!/usr/bin/env python3
"""
Structural chunking pipeline for SEC EDGAR filings.
Outputs chunks.jsonl — one JSON record per chunk.

Strategy:
  1. Parse 9-line metadata header → stored on every chunk
  2. Detect and discard XBRL preamble (Zone 2)
  3. Strip Table of Contents (pipe-delimited Part/Item lines)
  4. Split on "Item X." section headers (primary boundary)
  5. Sub-chunk large sections: paragraph → sentence boundaries
  6. Financial tables (pipe-row majority) kept as atomic chunks
"""

import re
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Iterator

CORPUS_DIR = Path("edgar_corpus")
OUTPUT_PATH = Path("chunks.jsonl")

MAX_CHUNK_CHARS = 2000  # ~500 tokens
OVERLAP_CHARS   = 300   # ~75 tokens

# ── Regexes ───────────────────────────────────────────────────────────────────

# Separator between metadata header and body
_SEP_RE = re.compile(r'^={10,}$', re.MULTILINE)

# First human-readable line after the XBRL preamble
_READABLE_RE = re.compile(
    r'(?:UNITED STATES\s+SECURITIES AND EXCHANGE COMMISSION'
    r'|FORM\s+10-[KQ]\b'
    r'|^Part\s+[IVX]+\s*$)',
    re.IGNORECASE | re.MULTILINE,
)

# Table of Contents entry — must have a trailing page number to be considered ToC:
#   "Item 1A. | Risk Factors | 5"  ← strip
#   "Item 1A. | Risk Factors"      ← keep (AMZN body section header)
_TOC_ENTRY_RE = re.compile(
    r'^(?:Part[\xa0 ][IVX]+|Item[\xa0 \t]+\d+[A-Z]?\.?)\s*\|.*\|\s*\d+\s*$'
)

# Section header split pattern — handles three corpus formats:
#   AAPL-style: "...None.Item 1.\xa0\xa0\xa0\xa0Business..."  (inline, 2+ non-breaking spaces)
#   BLK-style:  "\nItem 1. Business\n"                        (line-start, 1-2 spaces, capital)
#   AMZN-style: "\nItem 1. | Business\n"                      (line-start, space-pipe-space)
_SECTION_SPLIT_RE = re.compile(
    r'(Item\s+\d+[A-Z]?\.)(?:'
    r'\xa0{2,}'                       # AAPL: 2+ non-breaking spaces
    r'|[\xa0 \t]{1,2}\|[ \t]+'        # AMZN: whitespace then "| "
    r'|[ \t]{1,2}(?=[A-Z\[])'         # BLK: 1-2 spaces then capital letter
    r')',
    re.IGNORECASE | re.MULTILINE,
)

# Fallback canonical section names
_ITEM_NAMES: dict[str, str] = {
    "1":   "Business",
    "1A":  "Risk Factors",
    "1B":  "Unresolved Staff Comments",
    "2":   "Properties",
    "3":   "Legal Proceedings",
    "4":   "Mine Safety Disclosures",
    "5":   "Market for Registrant's Common Equity",
    "7":   "Management's Discussion and Analysis",
    "7A":  "Quantitative and Qualitative Disclosures About Market Risk",
    "8":   "Financial Statements and Supplementary Data",
    "9":   "Changes in and Disagreements with Accountants",
    "9A":  "Controls and Procedures",
    "9B":  "Other Information",
    "15":  "Exhibits and Financial Statement Schedules",
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    text: str
    ticker: str
    company: str
    filing_type: str
    filing_date: str
    report_period: str
    quarter: str
    cik: str
    section_id: str
    section_name: str
    content_type: str   # "text" | "table"
    chunk_index: int
    source_file: str


# ── Parsing helpers ───────────────────────────────────────────────────────────

def parse_header(raw: str) -> dict[str, str]:
    """Extract structured metadata from the 9-line file header."""
    sep = _SEP_RE.search(raw)
    header_block = raw[: sep.start()] if sep else raw[:500]
    key_map = {
        "Company":       "company",
        "Ticker":        "ticker",
        "Filing Type":   "filing_type",
        "Filing Date":   "filing_date",
        "Report Period": "report_period",
        "Quarter":       "quarter",
        "CIK":           "cik",
    }
    meta: dict[str, str] = {}
    for line in header_block.splitlines():
        for label, field in key_map.items():
            if line.startswith(label + ":"):
                meta[field] = line.split(":", 1)[1].strip()
                break
    return meta


def extract_body(raw: str) -> str:
    """Return Zone 3 text, skipping the XBRL preamble after the === separator."""
    sep = _SEP_RE.search(raw)
    if not sep:
        return raw
    after_sep = raw[sep.end():]

    m = _READABLE_RE.search(after_sep)
    if m:
        return after_sep[m.start():]

    # Fallback: skip lines that look like XBRL (very long, almost no spaces)
    for i, line in enumerate(after_sep.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) < 200 or stripped.count(" ") / len(stripped) > 0.05:
            return "\n".join(after_sep.splitlines()[i:])

    return after_sep


def strip_toc(body: str) -> str:
    """Remove Table of Contents entries (pipe-delimited lines that end with a page number)."""
    cleaned, toc_streak = [], 0
    for line in body.splitlines():
        if _TOC_ENTRY_RE.match(line):
            toc_streak += 1
            continue
        # Swallow one blank line immediately after a ToC block
        if toc_streak > 0 and not line.strip():
            toc_streak = 0
            continue
        toc_streak = 0
        cleaned.append(line)
    return "\n".join(cleaned)


def split_into_sections(body: str) -> list[tuple[str, str, str]]:
    """
    Split body on Item section headers.
    Returns list of (section_id, section_name, section_text).

    re.split with a capturing group produces:
        [pre_text, "Item 1.", content1, "Item 1A.", content2, ...]
    """
    parts = _SECTION_SPLIT_RE.split(body)

    sections: list[tuple[str, str, str]] = []

    if parts[0].strip():
        sections.append(("Preamble", "Filing Preamble", parts[0].strip()))

    for i in range(1, len(parts) - 1, 2):
        item_dot = parts[i].strip()          # e.g. "Item 1A."
        content  = parts[i + 1] if i + 1 < len(parts) else ""
        section_id, section_name = _parse_item_id(item_dot)
        if content.strip():
            sections.append((section_id, section_name, content.strip()))

    return sections


def _parse_item_id(item_dot: str) -> tuple[str, str]:
    """Parse 'Item 1A.' → ('Item 1A', 'Risk Factors')."""
    m = re.match(r'Item\s+(\d+[A-Z]?)\.', item_dot, re.IGNORECASE)
    if not m:
        return "Unknown", item_dot
    key = m.group(1).upper()
    return f"Item {key}", _ITEM_NAMES.get(key, f"Item {key}")


# ── Chunking helpers ──────────────────────────────────────────────────────────

def _is_table_heavy(text: str) -> bool:
    """True if text looks like a multi-row table (3+ lines, majority have 2+ pipes)."""
    lines = [l for l in text.splitlines() if l.strip()]
    return (
        len(lines) >= 3
        and sum(1 for l in lines if l.count("|") >= 2) / len(lines) > 0.5
    )


def _split_sentences(text: str, max_chars: int, overlap: int) -> list[str]:
    """Last-resort split on sentence boundaries."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= max_chars:
            current = (current + " " + sent).lstrip()
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if len(current) > overlap else current
            current = (tail + " " + sent).lstrip()
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


def chunk_section(
    text: str,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> list[tuple[str, bool]]:
    """
    Split a section into (chunk_text, is_table) pairs.

    Priority order:
      1. Keep financial tables (2+ pipes per row majority) as atomic chunks.
      2. Split on double-newline paragraph boundaries.
      3. If that yields oversized paragraphs (common in PDF-extracted filings
         where single \\n is the only line break), recurse on single-newline units.
      4. Fall back to sentence boundaries for still-oversized units.
    """
    if len(text) <= max_chars:
        return [(text, _is_table_heavy(text))]

    # Collect split units: try double-newline paragraphs first, then single lines
    double_paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if all(len(p) <= max_chars for p in double_paras) or len(double_paras) > 1:
        units = double_paras
        joiner = "\n\n"
    else:
        # Only one giant paragraph — fall back to single-line units
        units = [l.strip() for l in text.splitlines() if l.strip()]
        joiner = "\n"

    chunks: list[tuple[str, bool]] = []
    current = ""

    for unit in units:
        # Tables: emit as standalone atomic chunks
        if _is_table_heavy(unit):
            if current.strip():
                chunks.append((current.strip(), False))
                current = ""
            chunks.append((unit, True))
            continue

        if len(current) + len(unit) + len(joiner) <= max_chars:
            current = (current + joiner + unit) if current else unit
        else:
            if current.strip():
                chunks.append((current.strip(), False))
            tail = current[-overlap:] if len(current) > overlap else current

            if len(unit) <= max_chars:
                current = (tail.strip() + joiner + unit) if tail.strip() else unit
            else:
                # Unit itself exceeds limit — split on sentences
                seed = (tail.strip() + " " + unit) if tail.strip() else unit
                sent_chunks = _split_sentences(seed, max_chars, overlap)
                chunks.extend((c, False) for c in sent_chunks[:-1])
                current = sent_chunks[-1] if sent_chunks else ""

    if current.strip():
        chunks.append((current.strip(), False))

    return chunks or [(text[:max_chars], False)]


# ── Pipeline ──────────────────────────────────────────────────────────────────

def process_file(path: Path) -> Iterator[Chunk]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta = parse_header(raw)
    if not meta.get("ticker"):
        return

    body = strip_toc(extract_body(raw))

    for section_id, section_name, section_text in split_into_sections(body):
        for idx, (chunk_text, is_table) in enumerate(chunk_section(section_text)):
            if not chunk_text.strip():
                continue
            yield Chunk(
                text=chunk_text,
                ticker=meta.get("ticker", ""),
                company=meta.get("company", ""),
                filing_type=meta.get("filing_type", ""),
                filing_date=meta.get("filing_date", ""),
                report_period=meta.get("report_period", ""),
                quarter=meta.get("quarter", ""),
                cik=meta.get("cik", ""),
                section_id=section_id,
                section_name=section_name,
                content_type="table" if is_table else "text",
                chunk_index=idx,
                source_file=path.name,
            )


def main() -> None:
    files = sorted(CORPUS_DIR.glob("*_full.txt"))
    if not files:
        print(f"No *_full.txt files found in {CORPUS_DIR}/")
        return

    print(f"Processing {len(files)} files → {OUTPUT_PATH}\n")

    total = 0
    section_counts: dict[str, int] = {}

    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for path in files:
            file_chunks = list(process_file(path))
            for chunk in file_chunks:
                out.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
                section_counts[chunk.section_id] = (
                    section_counts.get(chunk.section_id, 0) + 1
                )
            total += len(file_chunks)
            print(f"  {path.name:<55} {len(file_chunks):>4} chunks")

    print(f"\nTotal chunks: {total:,}")
    print("\nChunks by section (top 12):")
    for sec, count in sorted(section_counts.items(), key=lambda x: -x[1])[:12]:
        bar = "█" * (count * 30 // max(section_counts.values()))
        print(f"  {sec:<14} {count:>5}  {bar}")


if __name__ == "__main__":
    main()
