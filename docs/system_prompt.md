# System Prompt Design

## The prompt

```
You are a financial analyst assistant specialising in SEC EDGAR filings.
You answer questions using only the source passages provided below.
Each passage is labelled [1], [2], ... and includes the company ticker,
filing type, filing date, and section.

Rules:
1. Cite every factual claim with its passage number in square brackets,
   e.g. [1] or [2][4]. Place citations immediately after the claim.
2. Only cite a passage if it directly supports the claim. Do not cite
   tangentially related passages.
3. If a question asks about a specific time period, prefer passages from
   the most recent filings within that period.
4. If the provided passages do not contain enough information to answer
   fully, state clearly what is and is not covered by the sources.
5. Do not speculate, infer, or draw on knowledge outside the provided
   passages.
6. When comparing multiple companies, address each company explicitly
   rather than generalising across them.
7. Use precise financial terminology. Do not paraphrase numbers — quote
   them exactly as they appear in the source.
8. Keep answers concise. Lead with the direct answer, then supporting
   detail.
```

---

## Rationale — rule by rule

**Rule 1 — cite every claim**  
Without mandatory inline citations the model produces fluent but unverifiable answers. Inline `[n]` markers placed immediately after each claim let readers (and a frontend) trace every sentence back to the exact passage. "Immediately after" is specified because models tend to batch citations at sentence ends if not instructed otherwise, making multi-claim sentences ambiguous.

**Rule 2 — direct support only**  
Without this constraint the model cites loosely related passages to appear well-sourced — e.g. citing a general business overview to support a specific revenue figure. This rule forces citation precision and reduces hallucinated citation relevance.

**Rule 3 — prefer recent filings**  
The corpus spans multiple years per company. Without recency guidance the model may cite a 2021 risk factor when a 2023 filing updates or supersedes it. The routing in `retrieve.py` already applies a `date_from` filter, but the LLM should also apply temporal judgement when multiple passages for the same topic are present.

**Rule 4 — state gaps explicitly**  
SEC filings do not disclose everything. If the retrieved passages lack the answer, the model must say so rather than filling the gap with general financial knowledge. This is the most important hallucination guard in financial RAG — a confident-sounding wrong number is worse than "the filings do not specify."

**Rule 5 — no outside knowledge**  
LLMs trained on financial data have internalised many facts about public companies. Without this rule the model silently blends retrieved context with training knowledge, making it impossible to audit whether an answer is grounded. The phrase "outside the provided passages" is deliberate — it is more concrete than "do not hallucinate."

**Rule 6 — address companies explicitly in comparisons**  
Multi-company questions (e.g. "How do Apple and Microsoft approach AI risk?") tend to produce generalised answers that do not clearly attribute claims. Explicitly naming companies in the answer makes citations unambiguous and is more useful for comparative analysis.

**Rule 7 — quote numbers exactly**  
Paraphrased numbers introduce rounding errors and unit ambiguities (millions vs billions). SEC filings are precise by design — the answer should preserve that precision.

**Rule 8 — concise, direct structure**  
Financial analysts read for conclusions first, then evidence. Leading with the direct answer before supporting detail respects that reading pattern and keeps answers scannable.

---

## Context block format

The prompt appends the retrieved passages after the system rules, before the question:

```
---
[1] AAPL · 10-K · 2023-10-27 · Item 1A — Risk Factors
<chunk text>

[2] TSLA · 10-K · 2023-01-26 · Item 1A — Risk Factors
<chunk text>

...

[N] ...
---

Question: <user question>
```

### Header line design

Each passage header contains four fields: ticker, filing type, filing date, section id — section name. This gives the model everything it needs to:

- Identify which company a claim belongs to
- Assess filing recency (date) when multiple passages cover the same topic
- Distinguish annual (10-K) from quarterly (10-Q) disclosures
- Locate the passage in the source document (section context)

The header is kept to one line to minimise token overhead. At 15 passages the headers add ~300 tokens — less than 4% of a typical 8,000-token prompt.

---

## Variations

### When no relevant passages are retrieved

If `HybridRetriever` returns zero chunks (filter fallback exhausted), the context block is replaced with a no-data notice:

```
No source passages were found for this question in the available filings.
```

The model is then expected to respond per Rule 4 — state that the sources do not cover the question.

### Tone variant — verbose/report style

For use cases that need longer narrative answers (e.g. generating a report section):

Replace Rule 8 with:

```
8. Write in a professional analyst report style. Use headers and bullet
   points where appropriate. Minimum 3 paragraphs for multi-part questions.
```

### Tone variant — brief/chatbot style

For conversational interfaces where brevity matters:

Replace Rule 8 with:

```
8. Keep the answer to 3–5 sentences maximum. Use plain language.
```

---

## What was deliberately excluded

**"You are a helpful assistant"** — generic helpfulness framing conflicts with strict grounding rules. A "helpful" model will try to fill gaps with outside knowledge. "Analyst assistant specialising in SEC filings" frames the role around the task domain.

**Chain-of-thought instructions** — asking the model to reason step-by-step before answering increases token cost and latency without meaningfully improving factual grounding for retrieval-based tasks. It is more useful for reasoning-heavy tasks (maths, logic) than for synthesis over retrieved text.

**"Do not make up information"** — this phrasing is ineffective. Models interpret it as a reminder rather than a constraint. Rule 4 (state gaps) and Rule 5 (no outside knowledge) are the operational equivalents — they describe the specific behaviours to avoid rather than the abstract concept.

**Formatting instructions for the citation list** — the answer module (`answer.py`) renders the citation list from the structured `Citation` objects, not from the LLM output. Asking the model to format a source list would produce duplicate rendering work and inconsistent formatting. The model's job is inline markers only.

---

## Known failure modes

**Marker omission** — smaller models (Llama 3.2, Mistral 7B) occasionally drop `[n]` markers on obvious or high-confidence claims. The validation step in `parse_citations()` catches phantom markers but cannot insert missing ones. Mitigation: reinforce citation rules in a one-line user-turn prefix: *"Remember to cite every claim with [n] markers."*

**Marker hallucination** — the model invents `[n]` values beyond the number of provided passages (e.g. `[17]` when only 15 passages were given). Caught and stripped by the phantom-citation validator in `parse_citations()`.

**Cross-passage blending** — the model synthesises a number or fact that does not appear verbatim in any single passage but is implied by combining two. This is technically not hallucination but violates the spirit of Rule 7. Difficult to detect automatically; flagged during evaluation when a cited passage does not contain the quoted number.

**Recency misjudgement** — when passages from different years describe the same metric, the model sometimes leads with the older figure and cites the newer one. Rule 3 addresses this partially; the retriever's date-sorted candidate ranking helps further.

**Over-hedging** — models that follow Rule 4 too aggressively add unnecessary caveats even when the passages clearly answer the question. Adjust with temperature (lower = more direct) or add to Rule 8: *"Do not add caveats that are not supported by the passages."*

---

## Prompt iterations log

| Version | Change | Reason |
|---|---|---|
| v1 | Initial draft — 5 rules, no recency rule | Baseline |
| v2 | Added Rule 3 (prefer recent filings) | Model was citing 2021 risk factors over 2023 updates |
| v2 | Added Rule 6 (address companies explicitly) | Multi-company answers were generalising across tickers |
| v3 | Changed "do not hallucinate" → Rule 5 (no outside knowledge) | More operational; easier for model to follow |
| v3 | Added "immediately after the claim" to Rule 1 | Model was batching citations at sentence ends |
| v4 | Added Rule 7 (quote numbers exactly) | Paraphrased figures introduced unit ambiguity |
| v4 | Replaced "helpful assistant" with domain framing | Reduced gap-filling with outside knowledge |
| v4 (10-Q) | Added data context block; updated section map for 10-Q structure | NVDA has mostly 10-Q filings; Item 2 = MD&A for 10-Qs, not Item 7 |
| v5 | LLM-based query routing with corpus context in `retrieve.py` | Category queries (e.g. "pharma companies") returned no tickers from regex; now resolved via LLM fallback |
| followup/v1 | Introduced `prompts/followup_system_prompt.md` for multi-turn sessions | Single-turn prompt produced stiff, report-like tone in conversation |

See `docs/system_prompt_change_history.md` for full prompt text at each version.
