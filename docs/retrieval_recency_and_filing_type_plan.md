# Retrieval: Recency Preference & 10-K Filing Type Plan

## Status: Implemented

Both fixes are implemented in `src/retrieval/retrieve.py`. Fix 1 (10-K inference for Item 1A queries) is in `QueryRouter._extract_filing_type()`. Fix 2 (recency decay) is in `_apply_recency_preference()` with `RECENCY_DECAY = 0.95`. The recency preference is applied when no explicit date window is set in the route (`date_from is None and date_to is None`).

---

## Problem

Two related issues produce stale or thin results for risk factor queries:

1. **Stale TSLA/AAPL risk factor chunks** — recent 10-Q Item 1A sections say "no material
   changes since the 10-K." They contain almost no text, so their vector similarity scores
   are low. Older 10-Qs that contained full risk factor text (e.g. TSLA 2022 Q1) rank higher
   purely on content match. The 10-K filings, which contain the authoritative full risk factor
   text, are not being preferentially selected.

2. **No default recency signal** — when a question has no temporal language, all filing years
   are treated equally. A 2021 chunk can beat a 2025 chunk on a tie in vector similarity.
   This means stale data surfaces for evergreen questions like "what are Tesla's risk factors?"

---

## Fix 1 — 10-K preference for Item 1A queries

### Why
Risk factors are written in full once per year in the 10-K (Item 1A). 10-Q Item 1A sections
either say "no material changes" (thin) or repeat a subset. For risk factor questions the
10-K is always the authoritative source.

### Where
`QueryRouter._extract_filing_type()` in `src/retrieval/retrieve.py`

### Current behaviour
Returns `"10-K"` only if the question explicitly says "annual" / "10-k".
Returns `None` otherwise, so no filing type filter is applied.

### Change
After extracting sections, if:
- `Item 1A` is the primary section signal (i.e. the question is about risk factors), AND
- the question does NOT explicitly request quarterly data ("quarterly", "10-q", "10q")

then return `"10-K"` as the inferred filing type.

```python
def _extract_filing_type(self, question: str) -> str | None:
    q = question.lower()
    if "annual" in q or "10-k" in q or "10k" in q:
        return "10-K"
    if "quarterly" in q or "10-q" in q or "10q" in q:
        return "10-Q"
    # Infer 10-K for risk factor questions
    sections = self._extract_sections(question)
    if sections == ["Item 1A"] or (len(sections) == 1 and "Item 1A" in sections):
        return "10-K"
    return None
```

### Safety net
The existing `_fallback_wheres()` already drops the `filing_type` filter at level 2 if
level 1 (ticker + section + filing_type) returns too few results. So if a company only has
10-Q Item 1A data, the fallback will still find it.

---

## Fix 2 — Default recency soft preference

### Why
Without a date signal in the question, all filings are treated as equally fresh. A soft
decay makes newer filings marginally preferred, reducing the chance that a 3-year-old chunk
beats a current one on a near-tie in vector similarity.

### Where
New helper applied inside `HybridRetriever.retrieve()`, after scoring, before balancing.
Similar to the existing `_apply_date_penalty()`.

### Change
Add `_apply_recency_preference()`. Only fires when `route.date_from` and `route.date_to`
are both `None` (i.e. no explicit date in the question). Applies a per-year decay to the
score based on filing age:

```python
RECENCY_DECAY = 0.95  # score multiplier per year of age

def _apply_recency_preference(
    candidates: list[tuple[float, dict]],
) -> list[tuple[float, dict]]:
    today = date.today()
    result = []
    for score, chunk in candidates:
        filing_date_str = chunk.get("filing_date", "")
        try:
            fd = date.fromisoformat(filing_date_str)
            years_old = (today - fd).days / 365.25
            score *= RECENCY_DECAY ** years_old
        except (ValueError, TypeError):
            pass
        result.append((score, chunk))
    return result
```

Effective multipliers at `RECENCY_DECAY = 0.95`:

| Filing age | Score multiplier |
|---|---|
| 0 years (today) | 1.00× |
| 1 year | 0.95× |
| 2 years | 0.90× |
| 3 years | 0.86× |
| 4 years | 0.81× |

This is intentionally gentle — a chunk from 2021 needs to be meaningfully more relevant
(not just on a marginal similarity tie) to beat a 2025 chunk.

### Call site
In `HybridRetriever.retrieve()`, apply after `_apply_date_penalty()`:

```python
if route.date_from is None and route.date_to is None:
    ranked = _apply_recency_preference(ranked)
```

---

## Implementation order

1. Fix 1 first — higher impact, narrower change, easy to verify
   - Update `_extract_filing_type()` as above
   - Smoke test: `python -m src.answer.answer "What are Tesla's risk factors?" --trace`
     → should show `Filing: 10-K`

2. Fix 2 second — broader change, verify recency shows in sources
   - Add `_apply_recency_preference()` and call site
   - Smoke test: `python -m src.answer.answer "What are Apple's biggest risks?" --trace`
     → TSLA/AAPL sources should now be 2024/2025, not 2022

---

## Risk notes

- **Fix 1 + multi-company query**: if a 3-company risk factor question includes one company
  with no 10-K in the corpus, the fallback levels handle it — level 2 drops `filing_type`,
  level 3 drops `section`, so that company will still contribute chunks.

- **Fix 2 decay base**: `0.95` is deliberately conservative. If answers become too skewed
  toward the very latest filing and miss important older context, lower to `0.97` or `0.98`.
  Do not set above `0.99` (negligible effect) or below `0.90` (too aggressive).

- **Interaction between fixes**: Fix 1 reduces the pool of candidates for Item 1A queries
  to 10-K only. Fix 2 then re-ranks within that pool by recency. The two work together
  without conflict.
