# Chunking Strategy: SEC EDGAR RAG Pipeline

## Context

The corpus is 246 SEC filings (89 10-K annual reports, 157 10-Q quarterly reports) from 54 major US public companies spanning 2022–2026. Files range from ~170KB (10-Q) to ~245KB (10-K). The RAG system must answer cross-company, cross-time business questions like risk factor comparisons and revenue trend analysis using a single LLM call.

## File Anatomy

Every file in `edgar_corpus/` has the same three-zone structure:

```
Zone 1 — Metadata header (lines 1–9)
────────────────────────────────────
Company: Apple Inc
Ticker: AAPL
Filing Type: 10-K (Annual Report)
Filing Date: 2022-10-28
Report Period: 2022-09-24
Quarter: 2022Q3
CIK: 0000320193
Source: SEC EDGAR
URL: https://...
============================================================

Zone 2 — XBRL preamble (~30 lines, one dense run-on line)
──────────────────────────────────────────────────────────
aapl-20220924false2022FY0000320193P1YP5Y...us-gaap:ProductMember2021-09-262022-09-24...

Zone 3 — Human-readable SEC filing text (rest of file)
───────────────────────────────────────────────────────
UNITED STATES SECURITIES AND EXCHANGE COMMISSION
...
Part I
Item 1.  Business
...
Item 1A. Risk Factors
...
```

Each zone requires different handling (see below).

---

## Strategy: Hierarchical Section-Based Chunking

### Zone 1 — Metadata header

**Action: extract, do not embed.**

Parse the 9 key-value lines and store as structured metadata attached to every chunk produced from that file. This enables metadata-filtered retrieval (e.g. filter to `ticker=NVDA, filing_type=10-K` before semantic search).

Fields extracted:
- `ticker`, `company`, `filing_type`, `filing_date`, `report_period`, `quarter`, `cik`

### Zone 2 — XBRL preamble

**Action: discard.**

The XBRL block is machine-readable structured financial data encoded as a compact inline string. It contains no sentence boundaries, no natural language, and would severely degrade embedding quality if included. It is not indexed.

Detection: everything between the `====` separator and the line containing `UNITED STATES SECURITIES AND EXCHANGE COMMISSION` (or the first `Part I` header).

### Zone 3 — SEC filing text

**Action: section-based splitting, then paragraph/size splitting within large sections.**

SEC filings follow a legally mandated structure. This structure maps directly onto the question types the RAG system needs to answer:

| Section | Content | Relevance |
|---|---|---|
| Item 1 | Business description | Company overview questions |
| Item 1A | Risk Factors | Risk comparison questions |
| Item 7 | MD&A (narrative financials) | Revenue, growth, outlook questions |
| Item 7A | Quantitative market risk | Market risk questions |
| Item 8 | Financial Statements | Precise numerical questions |
| Item 9A | Controls and Procedures | Governance questions |

#### Step 1 — Strip the Table of Contents

The ToC appears near the start of Zone 3 and lists `Item X. | Section Name | Page` entries. These duplicate section headers without content and pollute retrieval. They are identified by the pipe-separated pattern and discarded.

#### Step 2 — Split on Item headers (primary boundary)

Use the regex `r'^Item\s+\d+[A-Z]?\.'` (multiline) to detect section boundaries in the body text. Each Item section becomes an independent logical unit before further splitting.

Two-pass approach:
1. Find all `Item X.` positions in the body
2. Slice text between consecutive positions to get each section's content

#### Step 3 — Sub-chunk large sections

Item 1A (Risk Factors) and Item 7 (MD&A) regularly exceed 50KB. These are split further using the following priority order:

1. **Double newline** (`\n\n`) — preserves paragraph/risk-factor boundaries. Each risk factor in Item 1A is already a self-contained semantic unit separated by a blank line.
2. **Single newline** (`\n`) — fallback if a paragraph exceeds the size limit.
3. **Sentence boundary** (`. `) — last resort.

Target chunk size: **500–600 tokens** (~2,000–2,400 characters).  
Overlap: **75 tokens** (~300 characters) between consecutive chunks within the same section to avoid cutting context at chunk boundaries.

Small sections (< 200 tokens) are kept intact regardless of size.

#### Step 4 — Financial table preservation

Lines matching the pattern `| value | value |` (pipe-delimited tables) are identified before splitting. Tables are treated as atomic units and are never split mid-table, even if they exceed the target chunk size. They are tagged with `content_type: table` in metadata.

---

## Chunk Metadata Schema

Every chunk stored in the vector index carries:

```python
{
    # From file header
    "ticker":        "AAPL",
    "company":       "Apple Inc",
    "filing_type":   "10-K",
    "filing_date":   "2022-10-28",
    "report_period": "2022-09-24",
    "quarter":       "2022Q3",

    # From chunking
    "section_id":    "Item 1A",
    "section_name":  "Risk Factors",
    "content_type":  "text",          # or "table"
    "chunk_index":   3,               # position within section
    "source_file":   "AAPL_10K_2022Q3_2022-10-28_full.txt",
}
```

---

## Retrieval Design

At query time the metadata enables pre-filtering before semantic search, which significantly improves precision:

- **Company filter**: `ticker IN [AAPL, TSLA, JPM]`
- **Section filter**: `section_id = "Item 1A"` for risk questions, `section_id IN ["Item 7", "Item 8"]` for financial questions
- **Date range filter**: `filing_date >= "2023-01-01"` for recent filings
- **Filing type filter**: `filing_type = "10-K"` for annual comparisons

The query router parses the natural language question to infer which filters to apply before issuing the vector search. Retrieved chunks from multiple companies/filings are assembled into a single context block injected into the LLM prompt.

---

## Decisions and Tradeoffs

**Why not naive fixed-size chunking?**  
Fixed-size chunking (e.g. 512 tokens with overlap) cuts across section boundaries and mixes XBRL noise, ToC entries, boilerplate legal text, and actual content into the same chunks. For cross-company questions this produces retrieval results from incomparable parts of different filings.

**Why not one chunk per filing?**  
A full 10-K is ~245KB / ~60,000 tokens — far beyond context limits for retrieval and too coarse for embedding similarity.

**Why not one chunk per Item section?**  
Item 1A (Risk Factors) in a large 10-K is typically 8,000–15,000 tokens. A single embedding for the entire section averages over all risks and makes it hard to retrieve the specific risks relevant to a narrow question.

**Why keep financial tables intact?**  
Splitting a table mid-row produces chunks where numbers lose their column/row headers. A chunk containing `| 97,278 | 89,584 |` without headers is uninterpretable. The mild size increase is worth the accuracy gain.

**Why discard XBRL?**  
The XBRL block encodes the same financial facts that appear in the human-readable Item 8 tables, but in a format that produces meaningless embeddings. Including it would add noise without adding retrievable information.
