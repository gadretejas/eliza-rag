# SEC EDGAR RAG System

A retrieval-augmented generation system for answering business questions over SEC 10-K and 10-Q filings. Given a natural-language question, it retrieves relevant passages from a corpus of 246 filings across 54 major US companies and answers in a single LLM call.

## What it does

- Indexes annual (10-K) and quarterly (10-Q) reports from companies like AAPL, NVDA, MSFT, JPM, TSLA, and 49 others
- Retrieves filing sections that are semantically relevant to the question and match metadata filters (company, filing type, date range, section type)
- Produces a grounded, cited answer in one Claude API call

Example questions it handles:
- "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"
- "How has NVIDIA's revenue and growth outlook changed over the last two years?"
- "What regulatory risks do the major pharmaceutical companies face?"

## Project structure

```
.
├── README.md
├── chunk.py              # Chunking pipeline: corpus → chunks.jsonl
├── chunks.jsonl          # Output: 50,676 chunks with metadata (generated)
├── edgar_corpus/         # 246 SEC filings (.txt) + manifest.json
└── docs/
    ├── chunking_strategy.md      # Design rationale and tradeoff analysis
    └── chunking_implementation.md # Full implementation reference
```

## Setup

Python 3.11+ required. No external dependencies for the chunking step.

```bash
# Clone / unzip the repo, then:
python3 chunk.py          # produces chunks.jsonl (~50k chunks, takes ~30s)
```

The embedding and retrieval step requires an embedding model and a vector store. See the retrieval section below.

## Chunking

```bash
python3 chunk.py
```

Reads every `*_full.txt` file in `edgar_corpus/`, processes it through a structural chunking pipeline, and writes `chunks.jsonl`. Each line is a JSON object:

```json
{
  "text": "The Company's business faces risks including...",
  "ticker": "AAPL",
  "company": "Apple Inc",
  "filing_type": "10-K (Annual Report)",
  "filing_date": "2024-11-01",
  "report_period": "2024-09-28",
  "quarter": "2024Q3",
  "cik": "0000320193",
  "section_id": "Item 1A",
  "section_name": "Risk Factors",
  "content_type": "text",
  "chunk_index": 3,
  "source_file": "AAPL_10K_2024Q3_2024-11-01_full.txt"
}
```

See [docs/chunking_implementation.md](docs/chunking_implementation.md) for full details on the pipeline.

## Embedding and indexing

```bash
# Embed chunks.jsonl and load into a vector store
python3 embed.py          # generates embeddings, writes to vector index
```

Recommended: use `text-embedding-3-small` (OpenAI) or `voyage-finance-2` (Voyage AI, finance-tuned) with a local FAISS or ChromaDB index, or a hosted service like Pinecone.

## Retrieval

At query time:

1. Parse the question to infer metadata filters (tickers mentioned, date range, question type → section)
2. Embed the question
3. Run filtered vector search: `section_id IN [relevant items] AND ticker IN [mentioned companies]`
4. Rank and select the top-k chunks by similarity score

## Answering (single LLM call)

Retrieved chunks are assembled into a context block and injected into a prompt template:

```
You are a financial analyst assistant. Answer the question below using only
the provided SEC filing excerpts. Cite the company, filing type, and date
for each claim.

QUESTION: {question}

CONTEXT:
[Chunk 1 — AAPL 10-K 2024-11-01, Item 1A: Risk Factors]
{chunk_text}

[Chunk 2 — NVDA 10-K 2025-02-26, Item 1A: Risk Factors]
{chunk_text}
...

ANSWER:
```

The answer is produced in a single call to the Claude API (claude-sonnet-4-6 or claude-opus-4-7).

## Corpus

| Attribute | Value |
|---|---|
| Total filings | 246 |
| Annual reports (10-K) | 89 |
| Quarterly reports (10-Q) | 157 |
| Companies | 54 |
| Date range | 2022–2026 |
| Sectors | Technology, Financial, Healthcare, Consumer, Energy, Industrial |

Companies with full quarterly coverage (2023–2025): AAPL, AMZN, DIS, GOOG, JNJ, KO, MSFT, NVDA, PFE, TSLA, UNH, XOM, and others.

## Design decisions

Full design rationale is in [docs/chunking_strategy.md](docs/chunking_strategy.md).

The short version: structural section-based chunking (splitting on SEC Item headers) outperforms naive fixed-size chunking for this corpus because:
- The legal structure of SEC filings maps directly onto question types (risk questions → Item 1A, revenue questions → Item 7)
- Metadata filtering before vector search dramatically improves retrieval precision for cross-company comparison questions
- Financial tables are kept intact to preserve row/column relationships

## Evaluation

Quality was assessed by:
- Inspecting chunk size distribution (median 1,859 chars, P95 1,996 chars)
- Checking section coverage across filing formats (AAPL, AMZN, BLK styles all produce correct section splits)
- Verifying that table chunks preserve pipe-delimited structure
- Manually spot-checking retrieved chunks for representative demo questions
