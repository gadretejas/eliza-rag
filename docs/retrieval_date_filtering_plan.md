# Retrieval Date Filtering Plan

## Status: Implemented (including Fix 4 — candidate pool expansion)

All fixes are implemented in `src/retrieval/retrieve.py`. `RouteResult` now carries both `date_from` and `date_to`. The `_apply_date_filter()`, `_apply_date_penalty()`, and `_apply_recency_preference()` helpers are all present. ChromaDB's `$gte`/`$lte` operators only support numeric comparisons, so date filtering is done in Python post-retrieval rather than inside the ChromaDB `where` clause — this is equivalent in effect.

A fourth fix (Fix 4, below) was added after observing that temporal queries still returned stale data. The root cause was that recent chunks never appeared in the candidate pool at all — the semantic top-N was dominated by older, more verbose filings before the Python date filter could act.

---

## Problem

When a user asks a time-specific question (e.g. "as of 2024", "fiscal 2024"),
chunks from outside that year slip into the results. In the Tesla 2024 risk
factors query, sources from 2022 Q1 and 2025 Q1 appeared alongside the
intended 2024 10-K chunks.

Two distinct bugs cause this.

---

## Root Causes

### Bug 1 — `date_from` is a floor, not a range

`_extract_date_from()` in `QueryRouter` maps a year mention to a `$gte` filter:

```python
m = re.search(r"\b(20\d{2})\b", q)
if m:
    return f"{m.group(1)}-01-01"   # e.g. 2024-01-01
```

`$gte 2024-01-01` includes every filing from January 2024 onwards — including
2025 Q1. There is no upper bound (`date_to`), so future filings always leak in
when the user asks about a specific past year.

### Bug 2 — Fallback drops the date filter entirely

`_fallback_wheres()` relaxes filters when too few results are returned. The
second fallback removes `date_from` completely:

```python
if filters.get("sections"):
    yield self._build_where(
        {**filters, "sections": None, "date_from": None}
    )
yield None  # no filter at all
```

When the date-filtered query returns fewer than `top_k // 2` results, the
system widens to all years — which is why 2022 chunks appear for a 2024
question. A 2022 filing is not a valid substitute for a 2024 filing.

---

## Fixes

### Fix 1 — Add `date_to` for specific year mentions (highest priority)

**Where:** `QueryRouter._extract_date_from()` and `RouteResult`

Change `RouteResult` to carry both bounds:

```python
@dataclass
class RouteResult:
    tickers:      list[str]
    sections:     list[str]
    date_from:    str | None
    date_to:      str | None      # new
    filing_type:  str | None
```

Update `_extract_date_from()` to return a tuple `(date_from, date_to)`:

- Explicit year ("in 2024", "as of 2024", "fiscal 2024"):
  `date_from = 2024-01-01`, `date_to = 2024-12-31`
- Relative phrases ("last year", "recently", "current"):
  `date_from = today - N days`, `date_to = None` (open-ended, as today)
- No temporal signal: both `None`

Update `_build_where()` to emit `$lte` when `date_to` is set:

```python
if date_to:
    conditions.append({"filing_date": {"$lte": date_to}})
```

### Fix 2 — Widen date window in fallback instead of dropping it (medium priority)

**Where:** `VectorIndex._fallback_wheres()`

Replace the hard removal of `date_from` with a ±1 year window expansion:

```python
def _fallback_wheres(self, filters):
    # Level 1: full filters
    yield self._build_where(filters)

    # Level 2: widen date window by ±1 year instead of dropping it
    if filters.get("date_from") or filters.get("date_to"):
        widened = _widen_date_window(filters, years=1)
        yield self._build_where(widened)

    # Level 3: drop section filter, keep widened date
    if filters.get("sections"):
        widened = _widen_date_window(filters, years=1)
        yield self._build_where({**widened, "sections": None})

    # Level 4: no filter (last resort)
    yield None
```

`_widen_date_window(filters, years)` subtracts N years from `date_from` and
adds N years to `date_to` (capped at today). This keeps results temporally
anchored rather than opening to the full corpus.

### Fix 3 — Post-retrieval recency penalty (optional, low priority)

**Where:** `HybridRetriever.retrieve_with_trace()`, after candidate collection

After retrieval, apply a score penalty to chunks whose `filing_date` falls
outside the intended date window. The penalty should be a multiplier (e.g.
`0.85`) rather than a hard exclusion, so out-of-window chunks can still appear
at the bottom if nothing better exists.

```python
def _apply_date_penalty(
    candidates, date_from, date_to, penalty=0.85
):
    result = []
    for score, chunk in candidates:
        fd = chunk.get("filing_date", "")
        in_window = (
            (not date_from or fd >= date_from) and
            (not date_to   or fd <= date_to)
        )
        result.append((score * penalty if not in_window else score, chunk))
    return sorted(result, key=lambda x: x[0], reverse=True)
```

This is only needed if Fix 1 + Fix 2 leave edge cases (e.g. sparse coverage
for a specific year where no in-window chunks exist).

### Fix 4 — Expand candidate pool for date-bounded queries (added post-implementation)

**Where:** `HybridRetriever._retrieve_traced()`

**Problem discovered**: even with Fixes 1–3, temporal queries were returning stale data. Debugging revealed that recent NVDA filings had only 8–10 chunks in Item 2/MD&A while older filings had 26–32 chunks. The semantic top-35 candidates were entirely from 2022–2023, so the Python date filter in Fix 3 had nothing recent to promote.

**Fix**: when `date_from` or `date_to` is set, request 6× more candidates per company (up to 300):

```python
if route.date_from or route.date_to:
    search_k_per_company = min(cfg.candidates_per_company * 6, 300)
    search_k_global      = min(cfg.candidates_global * 4, 500)
```

This ensures chunks from shorter, newer filings are included in the candidate pool even when they rank lower on pure semantic similarity.

Additionally:
- Hard-filter threshold lowered from `top_k // 2` → `top_k // 3` (7 → 5 results required)
- Fallback penalty strengthened from `0.85×` → `0.40×`

---

## Implementation Sequence

| Step | Fix | Impact | Effort | Status |
|------|-----|--------|--------|--------|
| 1 | Add `date_to` for specific year mentions | Eliminates future-filing leakage | Low | Done |
| 2 | Widen date window in fallback | Eliminates past-filing leakage from fallback | Medium | Done |
| 3 | Post-retrieval recency penalty | Handles residual edge cases | Low | Done (0.40×) |
| 4 | Expand candidate pool for date-bounded queries | Ensures recent chunks appear in pool | Low | Done (6×) |

---

## Success Criteria

- `"What are Tesla's biggest risk factors as of 2024?"` returns only
  filings with `filing_date` between `2024-01-01` and `2024-12-31`
- `"What are Apple's risk factors recently?"` returns filings within the
  last 12 months, not decade-old chunks
- `"How has NVIDIA's revenue changed over the last two years?"` returns
  all 15 chunks from filings dated 2024-05 or later — verified passing
- A query for a year with sparse coverage gracefully applies a strong
  0.40× penalty rather than returning unconstrained results
- No query returns a filing outside the intended window unless fewer than
  5 in-window chunks exist across the entire corpus for that ticker
