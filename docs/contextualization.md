# Contextualization — Design Document

## Overview

Contextualization enriches each chunk before embedding by prepending two LLM-generated summaries:

```
[DOCUMENT CONTEXT]  ← 2-3 sentences about the filing as a whole
[SECTION CONTEXT]   ← 2-3 sentences about the dominant themes of this section
[CHUNK TEXT]        ← the original chunk passage
```

This makes the embedding carry company identity, fiscal period, and section-level theme information in the vector itself — not just in the metadata. A chunk that previously read:

> "The Company faces significant competition from companies that have greater resources..."

becomes:

> "[DOCUMENT] Apple Inc 10-K for fiscal year ended September 2024. Apple reported record revenue of $391 billion driven by 13% Services growth. The filing period coincides with rapid AI adoption across the technology sector.
>
> [SECTION] Item 1A — Risk Factors. This section identifies material risks including AI competitive threats from Google, Microsoft, and emerging models, supply chain concentration in TSMC, China revenue exposure (~18% of total), and evolving data privacy regulation across multiple jurisdictions.
>
> The Company faces significant competition from companies that have greater resources..."

The embedding of the enriched chunk now carries the company, fiscal period, and section themes as semantic signal — improving retrieval for queries that mention any of those concepts.

---

## Why two levels of context

**Document context** anchors:
- Company identity and filing type
- Fiscal period (quarter, year)
- Overall financial state at time of filing

**Section context** anchors:
- The dominant themes and key facts of this specific section
- What types of claims appear in this section
- Named entities and topics that recur throughout the section

Section context carries more retrieval lift than document context because it is closer to the chunk's actual content. Document context is most valuable for cross-period queries ("how has Apple's risk profile changed over time") where the period anchor matters. Both are included because they operate at different granularities and do not significantly overlap.

---

## What this is NOT doing

Prepending identical document context to all chunks from the same filing does **not** make those chunks retrieve together as a group. The section context and chunk text still differentiate them. What it does is ensure that a query mentioning "Apple FY2024" or "fiscal 2024 annual report" finds relevant chunks even when the chunk text itself doesn't contain those words.

Similarly, section context does not homogenise chunks within a section — it only adds shared thematic anchors. A query about "TSMC supply chain" will still rank a chunk that specifically discusses TSMC higher than a generic risk-factor chunk, because the chunk text differentiates them after the shared section context.

---

## Corpus facts

| Metric | Value |
|---|---|
| Unique documents | 246 |
| Unique (document, section) pairs | 2,736 |
| Total LLM calls to generate all contexts | 2,982 |
| Unique section IDs across corpus | 26 |

Section IDs present: `Item 1`, `Item 1A`, `Item 1B`, `Item 1C`, `Item 2`, `Item 3`, `Item 4`, `Item 5`, `Item 6`, `Item 7`, `Item 7A`, `Item 8`, `Item 9`, `Item 9A`, `Item 9B`, `Item 10`–`Item 16`, `Preamble`

---

## Embedding model compatibility

Enriched chunks are longer than original chunks. This matters for embedding models with short context windows.

| Embedding model | Max tokens | Avg enriched chunk | Status |
|---|---|---|---|
| `all-MiniLM-L6-v2` | 256 | ~700 | Severe truncation — contexts fill window, chunk text cut |
| `all-mpnet-base-v2` | 384 | ~700 | Significant truncation |
| `BAAI/bge-large-en-v1.5` | 512 | ~700 | Moderate truncation |
| `text-embedding-3-small` | 8,191 | ~700 | Fine |
| `voyage-finance-2` | 32,000 | ~700 | Fine |

**Conclusion:** contextualization is only effective with `text-embedding-3-small` or `voyage-finance-2`. The local `all-MiniLM-L6-v2` model would embed mostly context preamble with the chunk text truncated — producing embeddings that represent the section rather than the specific passage. Do not use contextualized chunks with local embedding models.

---

## Context generation prompts

### Document context prompt

Input: filing metadata + first 3,000 characters of the document body (~750 tokens).

```
You are summarising an SEC EDGAR filing for use in a retrieval system.
Write exactly 2-3 sentences capturing:
  1. The company name, filing type (10-K annual or 10-Q quarterly), and the
     fiscal period covered.
  2. One or two headline financial or strategic facts visible in the excerpt.

Be specific. Include numbers where present. Do not use bullet points or headers.
Write only the summary — no preamble, no label.

Company  : {company} ({ticker})
Filing   : {filing_type}
Filed    : {filing_date}
Period   : {report_period}

Excerpt:
{first_3000_chars}
```

**Example output:**
> Apple Inc filed its 10-K annual report for the fiscal year ended September 28, 2024. The company reported record annual revenue of $391.0 billion, up 2% year-over-year, with Services segment revenue reaching $96.2 billion and representing an increasing share of total revenue. The filing period coincides with broad industry adoption of generative AI and heightened regulatory scrutiny of large technology platforms.

### Section context prompt

Input: section metadata + first 3,000 characters of the section text (~750 tokens).

```
You are summarising one section of an SEC EDGAR filing for use in a retrieval
system. Write exactly 2-3 sentences capturing the dominant themes, key facts,
and named entities (companies, regulators, products, metrics) in this section.

This summary will be prepended to every chunk extracted from this section to
improve search retrieval. Be specific and information-dense.

Do not use bullet points or headers. Write only the summary — no preamble,
no label.

Company : {company} ({ticker})
Filing  : {filing_type}, filed {filing_date}
Section : {section_id} — {section_name}

Section text (excerpt):
{first_3000_chars}
```

**Example output:**
> This Risk Factors section identifies material risks facing Apple across regulatory, competitive, supply chain, and macroeconomic dimensions. Key risks include intensifying AI competition from Google, Microsoft, Meta, and emerging model providers; supply chain concentration with TSMC manufacturing substantially all Apple Silicon chips; China revenue exposure representing approximately 18% of total revenue subject to geopolitical and regulatory risk; and evolving data privacy legislation across the EU, US, and Asia-Pacific. The section also addresses product liability, intellectual property, and cybersecurity exposure.

---

## Storage design

Contexts are stored in two places:

### 1. `contexts.json` (generated by `contextualize.py`)

Keyed by `source_file` → `document_context` and per-section contexts. Serves as the durable record of generated contexts — allows re-embedding without re-generating.

```json
{
  "AAPL_10K_2024Q3_2024-11-01_full.txt": {
    "document_context": "Apple Inc filed its 10-K annual report...",
    "sections": {
      "Item 1A": "This Risk Factors section identifies material risks...",
      "Item 7":  "Management's Discussion covers revenue of $391B...",
      "Item 8":  "Financial Statements include consolidated balance sheets..."
    }
  }
}
```

### 2. ChromaDB collection metadata

Each chunk stored in ChromaDB includes the two context strings as separate metadata fields alongside the raw chunk text:

```python
metadata = {
    "ticker":           "AAPL",
    "filing_date":      "2024-11-01",
    "section_id":       "Item 1A",
    # ... other fields ...
    "document_context": "Apple Inc filed its 10-K...",
    "section_context":  "This Risk Factors section...",
    "text":             "The Company faces significant competition..."  # raw chunk
}
document = "[DOCUMENT] {doc_ctx}\n\n[SECTION] {sec_ctx}\n\n{chunk_text}"  # enriched — embedded
```

Keeping raw `text` and enriched `document` separate means:
- The embedding reflects enriched content
- `answer.py` passes raw `text` to the LLM (not the context preamble — the LLM sees a clean passage)
- Contexts can be updated independently of chunk text

---

## New script: `contextualize.py`

Sits between `chunk.py` and `embed.py` in the pipeline:

```
chunk.py → chunks.jsonl → contextualize.py → contexts.json → embed.py → ChromaDB
```

### Interface

```bash
# Generate all contexts (default: gpt-5.4-mini)
python3 contextualize.py

# Use a different model
python3 contextualize.py --model gpt-5.4
python3 contextualize.py --model ollama:llama3.2

# Resume interrupted run (skip already-generated contexts)
python3 contextualize.py --resume

# Regenerate contexts for one ticker only
python3 contextualize.py --ticker AAPL

# Custom output path
python3 contextualize.py --output data/contexts.json
```

### Key behaviours

**Grouping** — chunks are grouped by `source_file` for document contexts and by `(source_file, section_id)` for section contexts. Each group makes one LLM call.

**Resumability** — `--resume` loads existing `contexts.json` and skips any document/section already present. Critical for a 2,982-call job that may be interrupted.

**Batch ordering** — document contexts are generated first, then section contexts. If interrupted mid-section, `--resume` picks up from where it left off.

**Input truncation** — only the first 3,000 characters of each document/section are sent to the LLM. Beyond that, the context window would be wasted on boilerplate. 3,000 chars ≈ 750 tokens — well within all supported models.

**`embed.py` integration** — `embed.py` checks for `contexts.json` at startup. If found, it enriches each chunk before embedding. If not found, it embeds raw chunk text (backwards compatible).

---

## Cost and time estimates

### Inputs

| Metric | Value |
|---|---|
| Total LLM calls | 2,982 (246 doc + 2,736 section) |
| Avg input tokens per call | ~750 (first 3,000 chars ÷ 4) |
| Avg output tokens per call | ~120 (2-3 sentences) |
| Total input tokens | 2.24M |
| Total output tokens | 0.36M |

### API models

| Model | Input cost | Output cost | **Total** |
|---|---|---|---|
| `gpt-5.4-mini` (recommended) | $1.68 | $1.61 | **$3.29** |
| `gpt-5.4` | $5.60 | $5.36 | **$10.96** |

### Local models (Ollama)

Time is dominated by output generation. Input prefill is fast and excluded from estimates.

| Model | Hardware | Speed (tok/s) | **Estimated time** |
|---|---|---|---|
| `llama3.2` (3B) | Apple Silicon CPU | ~15 | 6h 37m |
| `llama3.2` (3B) | Apple Silicon Metal | ~45 | **2h 12m** |
| `llama3.1:8b` | Apple Silicon CPU | ~7 | 14h 12m |
| `llama3.1:8b` | Apple Silicon Metal | ~22 | 4h 31m |
| `mistral` (7B) | Apple Silicon CPU | ~8 | 12h 25m |
| `mistral` (7B) | Apple Silicon Metal | ~20 | 4h 58m |

> Token/sec figures are approximate for M-series Macs. Actual speed varies by chip generation (M1/M2/M3/M4) and available unified memory. Run `ollama run llama3.2` and observe tokens/sec in the terminal to calibrate for your machine.

**Context quality trade-off with local models:** `llama3.2` (3B) follows the summarisation prompt adequately but produces less information-dense contexts than `gpt-5.4-mini`. For a production-quality index, use `gpt-5.4-mini`. For a development index where cost is the constraint and time allows overnight generation, `llama3.2` with Metal acceleration (2h 12m) is viable.

### Recommendation

Use `gpt-5.4-mini` at **$3.29** — the lowest one-time cost with the highest context quality. This is generated once and stored in `contexts.json`; re-embedding with a different embedding model reuses the same contexts at no additional LLM cost.

---

## Pipeline integration summary

| Script | Change |
|---|---|
| `chunk.py` | None — outputs `chunks.jsonl` unchanged |
| `contextualize.py` | **New** — reads `chunks.jsonl`, generates contexts, writes `contexts.json` |
| `embed.py` | Check for `contexts.json`; if present, prepend contexts before embedding |
| `retrieve.py` | Pass raw `text` metadata field (not enriched document) to reranker and answer step |
| `answer.py` | None — already uses `chunk["text"]` not `chunk["document"]` |

---

## Failure modes

| Condition | Behaviour |
|---|---|
| `contexts.json` missing at embed time | `embed.py` falls back to raw chunk text — no error, contexts silently skipped |
| LLM returns empty string | Log warning, store empty string, continue — chunk will embed without context |
| API rate limit hit | Implement exponential backoff in `contextualize.py`; `--resume` allows retry without re-doing completed calls |
| Ollama not running | Hard exit with message: `Ollama not reachable — run: ollama serve` |
| Context generation interrupted | `--resume` restarts from last completed entry in `contexts.json` |
| Local model produces off-format output | Store as-is — a partial or verbose context is still better than no context for embedding purposes |
