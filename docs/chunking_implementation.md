# Chunking Implementation Reference

Complete technical reference for `chunk.py`. Covers every processing stage, the regex patterns, edge cases discovered during development, and the data contract for downstream consumers.

---

## Overview

`chunk.py` transforms the raw `edgar_corpus/` files into `chunks.jsonl`, a newline-delimited JSON file where each record is a self-contained chunk ready for embedding. The pipeline runs in under 30 seconds on a laptop and produces ~50,000 chunks from 246 filings.

```
edgar_corpus/*.txt
        │
        ▼
   parse_header()      ← extract structured metadata
        │
        ▼
   extract_body()      ← skip XBRL preamble
        │
        ▼
   strip_toc()         ← remove Table of Contents lines
        │
        ▼
 split_into_sections() ← split on "Item X." headers
        │
        ▼
  chunk_section()      ← sub-chunk large sections
        │
        ▼
   chunks.jsonl        ← 50,676 records
```

---

## File anatomy

Every file in `edgar_corpus/` has the same three-zone structure:

```
Zone 1 — Metadata header (lines 1–9)
════════════════════════════════════
Company: Apple Inc
Ticker: AAPL
Filing Type: 10-K (Annual Report)
Filing Date: 2022-10-28
Report Period: 2022-09-24
Quarter: 2022Q3
CIK: 0000320193
Source: SEC EDGAR
URL: https://...
============================================================   ← _SEP_RE

Zone 2 — XBRL preamble (dense encoded line, ~20–40 lines)
══════════════════════════════════════════════════════════
aapl-20220924false2022FY0000320193P1YP5Y...us-gaap:ProductMember...

Zone 3 — Human-readable SEC filing text
════════════════════════════════════════
UNITED STATES SECURITIES AND EXCHANGE COMMISSION
...
Part I
Item 1.   Business
...
```

---

## Stage 1: parse_header()

Extracts the 9 key-value lines from Zone 1 into a dict. This dict is attached to every chunk produced from the file as metadata.

```python
key_map = {
    "Company":       "company",
    "Ticker":        "ticker",
    "Filing Type":   "filing_type",
    "Filing Date":   "filing_date",
    "Report Period": "report_period",
    "Quarter":       "quarter",
    "CIK":           "cik",
}
```

The header ends at `_SEP_RE = re.compile(r'^={10,}$', re.MULTILINE)` — the `====` separator line. Only the block before this line is parsed for metadata.

Files without a `ticker` field are silently skipped (none in the current corpus).

---

## Stage 2: extract_body()

Locates where Zone 3 (human-readable text) begins and discards everything before it.

### Primary detection

Searches for the first occurrence of any anchor pattern:

```python
_READABLE_RE = re.compile(
    r'(?:UNITED STATES\s+SECURITIES AND EXCHANGE COMMISSION'
    r'|FORM\s+10-[KQ]\b'
    r'|^Part\s+[IVX]+\s*$)',
    re.IGNORECASE | re.MULTILINE,
)
```

The `UNITED STATES SECURITIES AND EXCHANGE COMMISSION` header appears in 10-Q files. `FORM 10-K` appears in annual reports that don't lead with the full SEC header. `^Part [IVX]+$` catches filings that begin directly with a Part heading.

### Fallback detection

If none of the anchor patterns match (edge cases in older filings), the fallback scans lines until it finds one that looks like natural language rather than XBRL:

```python
for i, line in enumerate(after_sep.splitlines()):
    stripped = line.strip()
    if not stripped:
        continue
    if len(stripped) < 200 or stripped.count(" ") / len(stripped) > 0.05:
        return "\n".join(after_sep.splitlines()[i:])
```

XBRL lines are dense and nearly space-free (ratio < 0.02). Any line under 200 chars or with > 5% spaces is treated as the start of readable content.

---

## Stage 3: strip_toc()

Removes Table of Contents entries from the body. The ToC duplicates section headers without content and would pollute retrieval if embedded.

### The ToC detection problem

The critical distinction between a ToC entry and a body section header differs by company:

| Format | ToC entry | Body section header |
|---|---|---|
| AAPL/AMZN | `Item 1A. \| Risk Factors \| 5` | `Item 1A. \| Risk Factors` |
| BLK/MSFT | `\| Risk Factors \| 5` | `Item 1A. Risk Factors` |

The reliable distinguishing feature is the **trailing page number**: ToC entries always end with `| N` (pipe followed by a page number), body headers do not.

### Pattern

```python
_TOC_ENTRY_RE = re.compile(
    r'^(?:Part[\xa0 ][IVX]+|Item[\xa0 \t]+\d+[A-Z]?\.?)\s*\|.*\|\s*\d+\s*$'
)
```

Breakdown:
- `^(?:Part[\xa0 ][IVX]+|Item[\xa0 \t]+\d+[A-Z]?\.?)` — line must start with a Part or Item header (including non-breaking space variants `\xa0`)
- `\s*\|\s*` — followed by a pipe
- `.*\|` — and at least one more pipe somewhere
- `\s*\d+\s*$` — ending with a page number

A blank line immediately after a ToC block is also swallowed to prevent empty leading lines in sections.

### Why not strip all pipe-containing Item lines?

Early implementation stripped any `Item X. |` line. This was wrong: AMZN body section headers also use the `Item 1. | Business` format (without a trailing page number). Stripping them removed all section markers from AMZN files, leaving only a single `Preamble` chunk per filing.

---

## Stage 4: split_into_sections()

Splits the cleaned body on Item section headers. Uses `re.split` with a capturing group, which interleaves captured delimiters into the result list:

```
re.split(r'(Item\s+\d+[A-Z]?\.)...', body)
→ [pre_text, "Item 1.", content1, "Item 1A.", content2, ...]
```

### The three-format problem

Three distinct header formats were found across the corpus. Each required its own alternation in the split regex:

#### AAPL-style (inline, non-breaking spaces)

PDF extraction from Apple's HTML filings produces Item headers embedded mid-line with `\xa0` (U+00A0, non-breaking space) as padding:

```
...None.Item 2.\xa0\xa0\xa0\xa0PropertiesThe Company's headquarters...
```

Marker: `\xa0{2,}` (two or more consecutive non-breaking spaces after the dot).

#### BLK/MSFT-style (line-start, regular space)

BlackRock, Microsoft, and others produce cleanly formatted text with Item headers on their own lines:

```
\nItem 1A. Risk Factors\n
```

Marker: `[ \t]{1,2}` followed by a capital letter or `[` (lookahead `(?=[A-Z\[])` ensures we don't match a lowercase continuation).

#### AMZN-style (line-start, pipe delimiter)

Amazon uses a pipe before the section name in body headers, the same character used in ToC entries but without a trailing page number:

```
\nItem 1A. | Risk Factors\n
```

Marker: `[\xa0 \t]{1,2}\|[ \t]+` (whitespace, then pipe, then space).

### Full pattern

```python
_SECTION_SPLIT_RE = re.compile(
    r'(Item\s+\d+[A-Z]?\.)(?:'
    r'\xa0{2,}'                       # AAPL: 2+ non-breaking spaces
    r'|[\xa0 \t]{1,2}\|[ \t]+'        # AMZN: whitespace then "| "
    r'|[ \t]{1,2}(?=[A-Z\[])'         # BLK: 1-2 spaces then capital letter
    r')',
    re.IGNORECASE | re.MULTILINE,
)
```

The capturing group `(Item\s+\d+[A-Z]?\.)` captures only the item identifier (e.g. `Item 1A.`). The non-capturing suffix that distinguishes body headers from inline references is consumed but not captured, so the result list alternates `[pre, "Item 1.", content, "Item 1A.", ...]` cleanly.

### Section naming

Section names are resolved from a lookup table keyed by item number, not parsed from the content. This is robust across all three formats because:
- AAPL content starts with `BusinessCompany Background...` (name runs into content)
- AMZN content starts with `Business\n...` (name on first line)
- BLK content starts with `Business\nOverview...` (name on first line, then newline)

Parsing the name from content would require different logic per format and is error-prone. The lookup table covers all standard SEC items.

---

## Stage 5: chunk_section()

Splits an individual section's text into final chunks of ~500 tokens each (2,000 characters), with 75-token (300-character) overlap.

### Split unit selection

The primary split boundary is the double newline `\n{2,}` (paragraph break). However, many filings in this corpus — particularly those converted from HTML — use only single `\n` throughout. In those files, the entire section is one giant paragraph:

```python
double_paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
if all(len(p) <= max_chars for p in double_paras) or len(double_paras) > 1:
    units = double_paras
    joiner = "\n\n"
else:
    # Single giant paragraph — fall back to line-level units
    units = [l.strip() for l in text.splitlines() if l.strip()]
    joiner = "\n"
```

The condition uses `len(double_paras) > 1` to prefer paragraph-level units whenever more than one paragraph exists. It falls back to single lines only when the entire section is one continuous block.

### Aggregation loop

Units (paragraphs or lines) are accumulated into `current` until the size limit is reached:

```python
if len(current) + len(unit) + len(joiner) <= max_chars:
    current = (current + joiner + unit) if current else unit
else:
    chunks.append(current.strip())
    tail = current[-overlap:] if len(current) > overlap else current
    current = (tail.strip() + joiner + unit) if tail.strip() else unit
```

The `tail` carries the last `overlap` characters of the previous chunk into the next one to preserve context across boundaries.

### Table preservation

Blocks where the majority of lines contain 2+ pipe characters are treated as financial tables and emitted as standalone atomic chunks, regardless of size:

```python
def _is_table_heavy(text: str) -> bool:
    lines = [l for l in text.splitlines() if l.strip()]
    return (
        len(lines) >= 3
        and sum(1 for l in lines if l.count("|") >= 2) / len(lines) > 0.5
    )
```

Requiring `len(lines) >= 3` prevents single-line pipe expressions (e.g. `California | 94-2404110`) from being misclassified as tables. When detected, the in-progress `current` buffer is flushed first, then the table is appended as its own chunk tagged `content_type: "table"`.

### Sentence fallback

If an individual unit (a paragraph or line) still exceeds `max_chars` after the above steps, it is split on sentence boundaries:

```python
sentences = re.split(r'(?<=[.!?])\s+', text)
```

This is a last resort used for extremely long individual paragraphs (e.g., a single 5,000-character risk factor bullet point in an older filing format).

---

## Output schema

Every record in `chunks.jsonl`:

| Field | Type | Example | Notes |
|---|---|---|---|
| `text` | str | `"The Company faces risks..."` | The embeddable text |
| `ticker` | str | `"AAPL"` | For metadata filtering |
| `company` | str | `"Apple Inc"` | Human display |
| `filing_type` | str | `"10-K (Annual Report)"` | `"10-K..."` or `"10-Q..."` |
| `filing_date` | str | `"2024-11-01"` | ISO date of filing submission |
| `report_period` | str | `"2024-09-28"` | End of the reporting period |
| `quarter` | str | `"2024Q3"` | Fiscal quarter (may be empty for 10-K) |
| `cik` | str | `"0000320193"` | SEC Central Index Key |
| `section_id` | str | `"Item 1A"` | Normalized item identifier |
| `section_name` | str | `"Risk Factors"` | Human-readable section name |
| `content_type` | str | `"text"` | `"text"` or `"table"` |
| `chunk_index` | int | `3` | Position within the section |
| `source_file` | str | `"AAPL_10K_2024Q3_2024-11-01_full.txt"` | Provenance |

---

## Corpus statistics (run results)

| Metric | Value |
|---|---|
| Input files | 246 |
| Output chunks | 50,676 |
| Median chunk size | 1,859 chars |
| Mean chunk size | 1,652 chars |
| P95 chunk size | 1,996 chars |
| Chunks > 4,000 chars | 67 (0.1%) |
| Table chunks | 248 |

Top sections by chunk count:

| Section | Chunks | Description |
|---|---|---|
| Item 1A | 10,689 | Risk Factors |
| Item 1 | 8,751 | Business |
| Preamble | 8,173 | Filing cover page and boilerplate |
| Item 8 | 5,860 | Financial Statements |
| Item 2 | 4,196 | Properties / MD&A sub-items |
| Item 7 | 3,599 | Management's Discussion and Analysis |

---

## Configuration

Two constants at the top of `chunk.py` control chunk sizing:

```python
MAX_CHUNK_CHARS = 2000  # ~500 tokens at ~4 chars/token
OVERLAP_CHARS   = 300   # ~75 tokens carried into the next chunk
```

To change the corpus directory or output path:

```python
CORPUS_DIR  = Path("edgar_corpus")
OUTPUT_PATH = Path("chunks.jsonl")
```

---

## Running

The script is at `src/pipeline/chunk.py`. Run as a module:

```bash
python -m src.pipeline.chunk
```

No dependencies beyond the Python standard library. Processes all 246 files and writes `chunks.jsonl` in approximately 30 seconds. Progress is printed per file with a chunk count.

To process a single file in a Python session:

```python
from src.pipeline.chunk import process_file
from pathlib import Path

for chunk in process_file(Path("edgar_corpus/NVDA_10K_2025-02-26_full.txt")):
    print(chunk.section_id, chunk.chunk_index, len(chunk.text))
```

---

## Known limitations

**Inline item references are not filtered.** Text like "see Item 1A for risk factors" contains the same `Item 1A` string as a section header. The split regex requires specific whitespace and/or pipe patterns after the dot to avoid matching these, but unusual formatting in older filings could occasionally produce a false split.

**XBRL fallback is heuristic.** The primary XBRL detection anchors on known SEC header strings. The fallback (space-density threshold) works for the current corpus but could misplace the body start in a highly unusual filing.

**Non-standard items.** Some companies include non-standard Items (e.g., `Item 1C` for cybersecurity disclosures, added by the SEC in 2023). These are split and indexed correctly but fall back to the generic section name `"Item 1C"` since they are not in `_ITEM_NAMES`.
