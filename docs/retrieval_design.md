# Retrieval Design

Design reference for the retrieval layer of the SEC EDGAR RAG system. Covers the shared infrastructure, the standard hybrid pipeline, and the optional agentic retriever that can be enabled via configuration.

---

## Table of contents

1. [Overview](#overview)
2. [Shared infrastructure](#shared-infrastructure)
   - [Query router](#query-router)
   - [Vector index](#vector-index)
   - [Re-ranker](#re-ranker)
   - [Per-company balancing](#per-company-balancing)
3. [Standard retriever](#standard-retriever)
   - [Pipeline walkthrough](#pipeline-walkthrough)
   - [Worked example](#worked-example-standard)
   - [Failure modes](#failure-modes-standard)
4. [Agentic retriever](#agentic-retriever)
   - [When to use it](#when-to-use-it)
   - [Tools](#tools)
   - [Agent loop](#agent-loop)
   - [Worked example](#worked-example-agentic)
   - [Failure modes](#failure-modes-agentic)
5. [Configuration](#configuration)
6. [Interface contract](#interface-contract)
7. [Decision log](#decision-log)

---

## Overview

Both retrievers implement the same interface:

```python
retriever.retrieve(question: str) -> list[Chunk]
```

The answer layer calls `retrieve()` and receives a ranked list of chunks. It does not know or care which retriever is active. The mode is controlled entirely by `RetrieverConfig`.

```
Question
    │
    ▼
┌───────────────────────────────────────────────┐
│              RetrieverConfig                  │
│  mode: "standard" | "agentic"                 │
└───────────────────┬───────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
 HybridRetriever         AgenticRetriever
 (single-shot)           (iterative, tool-use)
        │                       │
        └───────────┬───────────┘
                    │
                    ▼
             list[Chunk]  (top-k, ranked)
                    │
                    ▼
            Single LLM answer call
```

---

## Shared infrastructure

Both retrievers are built on the same three components. These are not duplicated — `AgenticRetriever` wraps `HybridRetriever`'s primitives as tool implementations.

### Query router

A lightweight keyword heuristic that parses the question into structured retrieval parameters. No LLM call — deterministic and fast (~1ms).

```python
@dataclass
class RouteResult:
    tickers:    list[str]       # companies explicitly mentioned
    sections:   list[str]       # section_ids to target
    date_from:  str | None      # ISO date lower bound, or None
    filing_type: str | None     # "10-K" | "10-Q" | None
```

**Ticker extraction**

Matches company names and tickers against a lookup table of all 54 companies in the corpus. Both canonical forms are recognised: "Apple" → `AAPL`, "AAPL" → `AAPL`, "Apple Inc" → `AAPL`.

**Section mapping**

Question intent → target `section_id`s:

| Signal words | Sections targeted |
|---|---|
| "risk", "risks", "exposure", "threat", "danger" | `Item 1A` |
| "revenue", "growth", "sales", "outlook", "guidance", "forecast" | `Item 7`, `Item 8` |
| "regulatory", "regulation", "compliance", "FDA", "SEC", "legal" | `Item 1A`, `Item 1` |
| "business", "operations", "products", "services", "segment" | `Item 1` |
| "financial", "earnings", "profit", "margin", "EPS", "income" | `Item 7`, `Item 8` |
| "strategy", "acquisition", "investment", "capital" | `Item 7`, `Item 1` |
| no clear signal | `Item 1A`, `Item 1`, `Item 7` (broad) |

**Temporal parsing**

| Question phrase | `date_from` |
|---|---|
| "last two years", "past two years" | today − 2 years |
| "last year", "past year", "recent", "recently" | today − 1 year |
| "this year", "current" | today − 6 months |
| "2024", "in 2024" | 2024-01-01 |
| "since 2023" | 2023-01-01 |
| no temporal signal | None (no date filter) |

When no tickers are found, `tickers` is empty and the retriever fans out across all companies in the filtered section.

---

### Vector index

An ANN index over the embeddings of all chunk `text` fields. Each vector stores the full chunk metadata as a payload, enabling pre-filter queries without a secondary lookup.

**Current setup**

The vector store is a ChromaDB persistent collection (HNSW-backed). The ChromaDB embedded client (`PersistentClient`) is used rather than a Docker HTTP service — simpler deployment with the same API. See `docs/chromadb_migration.md` for details.

| Scenario | Index | Embedding model |
|---|---|---|
| Local / no API key | ChromaDB + HNSW | `all-MiniLM-L6-v2` (sentence-transformers) |
| Production | ChromaDB + HNSW | `text-embedding-3-small` (OpenAI) or `voyage-finance-2` |

`voyage-finance-2` is worth considering — it is explicitly trained on financial documents and outperforms general-purpose models on financial retrieval benchmarks. The embedding dimension is 1024 vs 1536 for `text-embedding-3-small`, which also reduces index size.

**Query at retrieval time**

```python
index.search(
    vector=embed(question),
    filter={
        "ticker":      {"$in": tickers},       # omit if tickers is empty
        "section_id":  {"$in": sections},
        "filing_date": {"$gte": date_from},     # omit if date_from is None
    },
    top_k=candidates_per_company,
)
```

---

### Re-ranker

A cross-encoder that scores `(question, chunk_text)` pairs jointly. Unlike bi-encoder embeddings — which encode query and document independently — a cross-encoder attends to both simultaneously, producing more accurate relevance scores at the cost of being slower and non-indexable.

**Why re-ranking is necessary here**

Vector search optimises for semantic similarity between the query embedding and chunk embeddings. For financial filings this is insufficient because:

- The word "risk" appears in thousands of chunks across every section. Embeddings alone cannot distinguish "supply chain risk" from "regulatory risk" at the precision needed for comparison questions.
- Multi-aspect queries ("risks AND how they are addressing them") get their embedding averaged over both aspects. The cross-encoder sees the full question and can score completeness.
- Temporal language ("changed over the last two years") is not captured in chunk embeddings at all. The re-ranker can up-score chunks that discuss change vs static descriptions.

**Recommended re-rankers**

| Option | Latency (75 chunks) | Notes |
|---|---|---|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | ~150ms CPU | Local, no API key, good baseline |
| `BAAI/bge-reranker-v2-m3` | ~250ms CPU | Stronger, multilingual |
| Cohere Rerank (`rerank-english-v3.0`) | ~300ms (network) | Hosted, strong general quality |
| Voyage `rerank-2` | ~300ms (network) | Hosted, finance-aware |

For a live demo, `ms-marco-MiniLM-L-6-v2` is the safe default: no external dependency, predictable latency, easy to explain. Cohere or Voyage Rerank is the upgrade path if retrieval quality is insufficient on financial terminology.

---

### Per-company balancing

When a question names multiple companies, a global top-k after re-ranking can be dominated by one company's chunks (e.g. if NVDA's filings are longer and more verbose than JPM's, NVDA chunks will have higher raw relevance scores for the same question).

Balancing enforces a minimum floor after re-ranking:

```
min_per_company = max(2, k // len(tickers))
```

**Algorithm**

1. Sort all candidates by re-rank score (descending)
2. Fill `min_per_company` slots for each mentioned ticker, in score order
3. Fill remaining `k − (min_per_company × len(tickers))` slots with the highest-scored chunks regardless of company

This guarantees every mentioned company has at least `min_per_company` chunks in the final context, while still preferring higher-quality chunks for the open slots.

---

## Standard retriever

### Pipeline walkthrough

```
Question
    │
    ▼  (~1ms)
Query Router
    │  RouteResult{tickers, sections, date_from}
    │
    ▼  (~50–100ms)
Per-ticker ANN search
    │  top 20 candidates per ticker
    │  (metadata pre-filter applied)
    │
    ▼
Pool all candidates
    │  N = 20 × len(tickers), or 50 if no tickers
    │
    ▼  (~150–300ms)
Re-ranker
    │  score each (question, chunk) pair
    │
    ▼  (<1ms)
Balanced top-k selection
    │  k=15, min_per_company enforced
    │
    ▼
list[Chunk]  →  answer call
```

**Total latency estimate**: 200–400ms for a 3-company question with local re-ranker.

### Worked example (standard)

Question: *"What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"*

**Router output**
```
tickers:   [AAPL, TSLA, JPM]
sections:  [Item 1A]
date_from: None
```

**ANN search**
- 20 × AAPL `Item 1A` candidates
- 20 × TSLA `Item 1A` candidates
- 20 × JPM `Item 1A` candidates
- Pool: 60 chunks

**Re-ranker**
Scores all 60 against "primary risk factors facing Apple, Tesla, JPMorgan comparison". The top scores are likely the most specific and substantive risk descriptions from the most recent 10-K for each company.

**Balanced selection**
`min_per_company = max(2, 15 // 3) = 5`

Final context: 5 AAPL + 5 TSLA + 5 JPM chunks = 15 chunks → answer call.

### Failure modes (standard)

| Scenario | What happens | Mitigation |
|---|---|---|
| No tickers in question | No company filter → searches all companies in target sections | Acceptable; returns broadly relevant chunks |
| Mentioned company not in corpus | Router finds no match → that company is skipped silently | Add a warning to the response if any mentioned company had zero chunks |
| Question implies a section not in the mapping | Falls back to broad default sections | Acceptable for the demo question set |
| Very recent question date beyond corpus coverage | Date filter returns few or zero results | Fall back to no date filter if filtered result count < k |

---

## Agentic retriever

The agentic retriever wraps the standard pipeline's building blocks and lets a lightweight LLM agent decide what to retrieve, observe the results, and issue further retrievals if needed. It is designed for questions where the right retrieval strategy is not knowable from the question text alone.

### When to use it

Enable agentic mode when the question is likely to benefit from iterative refinement:

| Question type | Standard sufficient? | Agentic adds value? |
|---|---|---|
| Named companies, clear section intent | Yes | No — overhead without gain |
| Discovery ("which pharma companies...") | No | Yes — needs to fan out first |
| Multi-hop across time ("risks in 2023 that materialised by 2025") | No | Yes — needs two targeted lookups |
| Ambiguous scope ("latest Apple AI guidance") | Sometimes | Yes — needs to check what "latest" is |
| Trend analysis across multiple filings | Sometimes | Yes — iterates across dates |

The configuration exposes this as a simple toggle. The front-end can surface it as a "Deep Research" mode.

### Tools

The agent has access to four retrieval tools. Each tool internally runs the same ANN search + re-rank as the standard pipeline.

---

#### `search_section`

Targeted retrieval scoped to specific companies and a specific section.

```
search_section(
    tickers:    list[str],     # e.g. ["PFE", "JNJ", "MRK"]
    section_id: str,           # e.g. "Item 1A"
    query:      str,           # semantic search query
    date_from:  str | None,    # ISO date lower bound
    top_k:      int = 10,
) -> list[Chunk]
```

Use when: companies are known and the relevant section is clear.

---

#### `search_company`

Broad retrieval across all sections for one company.

```
search_company(
    ticker:    str,            # e.g. "NVDA"
    query:     str,
    date_from: str | None,
    top_k:     int = 15,
) -> list[Chunk]
```

Use when: the company is known but the relevant section is unclear, or the question spans multiple sections.

---

#### `search_across`

Wide retrieval across all companies in a given section. No ticker filter.

```
search_across(
    query:      str,
    section_id: str,
    date_from:  str | None,
    top_k:      int = 20,
) -> list[Chunk]
```

Use when: no specific companies are named and the question is about a category (e.g. "pharma companies", "major banks").

---

#### `get_filing_list`

Returns metadata about available filings — no text, no embeddings. Lets the agent check what coverage exists before committing to a retrieval.

```
get_filing_list(
    ticker:       str | None,        # None = all companies
    filing_type:  str | None,        # "10-K" | "10-Q" | None
    date_from:    str | None,
    date_to:      str | None,
) -> list[FilingMetadata]            # {ticker, filing_type, filing_date, source_file}
```

Use when: the question references time periods and the agent needs to know which filings are available before searching.

---

### Agent loop

The agent follows a ReAct (Reason → Act → Observe) loop. Each iteration is one LLM call to the agent model (Haiku by default).

```
┌─────────────────────────────────────────────────────┐
│  Input: question + accumulated context so far       │
│                                                     │
│  Reason: "What do I still need to retrieve?"        │
│  Act:    call one or more tools (in parallel)       │
│  Observe: read tool results, update context         │
│                                                     │
│  Repeat until:                                      │
│    - agent returns done signal                      │
│    - max_iterations reached (default: 3)            │
│    - token_budget exceeded (default: 80k tokens)    │
└─────────────────────────────────────────────────────┘
```

**Parallel tool calls**

Claude's tool use API supports multiple tool calls in a single turn. For comparison questions with known companies, the agent can dispatch all per-company retrievals in parallel in iteration 1, observe results, and decide whether a second pass is needed — rather than serialising one company at a time.

**Context accumulation**

Chunks accumulate across iterations. Before passing to the final answer call, two cleanup steps run:

1. **Deduplication** — remove chunks with the same `(source_file, chunk_index)` that appeared in multiple iterations
2. **Final re-rank** — re-rank all accumulated chunks against the original question and take the top-k. This ensures the final context is the best chunks across all iterations, not just from the last one.

**Agent system prompt (sketch)**

```
You are a retrieval agent for a financial document search system.
Your job is to retrieve the most relevant passages from SEC filings
to answer the user's question.

You have access to the following tools: [tool descriptions]

Rules:
- Issue multiple tool calls in parallel when retrieving for different companies.
- Call get_filing_list first if you are unsure which time periods are covered.
- Stop and return done when you have sufficient context to answer the question.
- Do not exceed 3 retrieval iterations.
- Prefer the most recent 10-K for company overviews; include multiple filings
  when the question asks about change over time.
```

### Worked example (agentic)

Question: *"What regulatory risks do the major pharmaceutical companies face, and how are they addressing them?"*

**Iteration 1**

Reason: "No specific companies named. Need to find which pharma companies are in the corpus and retrieve their regulatory risk disclosures."

Act (parallel):
```
search_across("regulatory risk FDA approval drug pricing", "Item 1A", date_from="2024-01-01", top_k=25)
```

Observe: Chunks returned from PFE, JNJ, MRK, LLY, ABBV. Good risk identification coverage.

**Iteration 2**

Reason: "Have risk identification. Question also asks how they're *addressing* the risks — need forward-looking mitigation language. MD&A sections typically discuss responses to regulatory challenges."

Act (parallel):
```
search_section(["PFE", "JNJ", "MRK", "LLY", "ABBV"], "Item 7",
               "regulatory strategy pipeline mitigation compliance", date_from="2024-01-01", top_k=10)
```

Observe: MD&A chunks with pipeline diversification, compliance investment, and lobbying/engagement strategies.

**Iteration 3**

Reason: "Have both risk identification and mitigation context across 5 pharma companies. Context is sufficient."

Act: done

**Final re-rank + dedup → top 15 chunks → answer call**

---

### Failure modes (agentic)

| Scenario | What happens | Mitigation |
|---|---|---|
| Agent loops without converging | Hits `max_iterations` hard cap | Return accumulated context at cap |
| Agent calls a tool with a ticker not in corpus | Vector search returns empty | Tool returns `[]` with a "no results" note; agent adapts |
| Token budget exceeded mid-loop | Loop terminates early | Trigger final re-rank on whatever is accumulated |
| Agent model makes a poor tool choice | Less relevant chunks than standard pipeline | Standard pipeline is always the fallback (`mode="standard"`) |
| Agent model is unavailable | Hard failure | Catch and fall back to standard pipeline automatically |

---

## Configuration

```python
@dataclass
class RetrieverConfig:
    # Mode selection
    mode: Literal["standard", "agentic"] = "standard"

    # Standard pipeline parameters
    top_k: int = 15                   # final chunks passed to LLM
    candidates_per_company: int = 20  # ANN candidates per ticker
    rerank: bool = True
    reranker: Literal["local", "cohere", "voyage"] = "local"

    # Balancing
    min_per_company: int | None = None
    # None = auto-compute as max(2, top_k // len(tickers))

    # Agentic parameters (only used when mode="agentic")
    max_iterations: int = 3
    token_budget: int = 80_000
    agent_model: str = "claude-haiku-4-5-20251001"
    parallel_tools: bool = True
    fallback_to_standard: bool = True
    # If True, any agent failure falls back to HybridRetriever silently
```

**Selecting a configuration at runtime**

```python
def get_retriever(config: RetrieverConfig) -> BaseRetriever:
    if config.mode == "agentic":
        return AgenticRetriever(config)
    return HybridRetriever(config)
```

---

## Interface contract

Both retrievers satisfy this interface:

```python
class BaseRetriever(ABC):

    @abstractmethod
    def retrieve(self, question: str) -> list[Chunk]:
        """
        Return top-k chunks relevant to question.
        Chunks are ordered by descending relevance score.
        Metadata filters and balancing are applied internally.
        """

    def retrieve_with_trace(self, question: str) -> RetrievalTrace:
        """
        Same as retrieve() but also returns diagnostic information:
        - router output (tickers, sections, date_from)
        - candidate counts per stage
        - re-ranker scores
        - agent iteration log (agentic mode only)
        Used by the front-end debug panel and for evaluation.
        """
```

`RetrievalTrace` is the data structure surfaced in the front-end when "show reasoning" is enabled. In agentic mode it includes the full ReAct trace: each iteration's reason, tool calls, and observations.

---

## Decision log

**Why not use another LLM call for query routing?**
The query router is a keyword heuristic, not an LLM call. An LLM-based router would be more robust for ambiguous phrasing but adds latency and a failure mode in the hot path. The demo question set is narrow enough that a keyword heuristic covers all expected inputs reliably.

**Why re-rank before balancing, not after?**
Re-ranking before balancing means the re-ranker sees the full candidate pool and assigns accurate scores. Balancing post-re-rank then enforces coverage without distorting scores. Balancing before re-ranking would let the re-ranker work on a potentially unrepresentative subset.

**Why is `min_per_company` a floor, not a hard equal split?**
Equal splits (5 chunks per company regardless of quality) can force low-quality chunks into the context if one company's filings don't have strong matches. A floor with open slots filled by best-available-score gives balanced coverage without penalising good questions.

**Why Haiku for the agent model?**
Agent iterations are low-stakes reasoning tasks: "what should I search for next?" The cost difference between Haiku and Sonnet is ~20x per token. With up to 3 iterations per query, using Sonnet for the agent would make the agentic mode significantly more expensive than the standard pipeline. Haiku is fast and cheap; Sonnet is reserved for the answer call where quality matters.

**Why cap agentic iterations at 3?**
Empirically, the demo question set is answerable in 1–2 iterations. The cap of 3 exists as a safety net, not an expected limit. Beyond 3 iterations the marginal value of additional retrieval is low and the latency cost becomes noticeable in a live demo.

**Why does `AgenticRetriever` wrap `HybridRetriever`'s primitives rather than implementing its own retrieval?**
Code reuse and correctness consistency. The vector search, re-ranking, and balancing logic has been tested and debugged in one place. The agent is an orchestration layer — it decides *what* to retrieve, not *how* to retrieve it.
