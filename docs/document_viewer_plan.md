# Document Viewer — Design & Implementation Plan

## Status: Implemented

This feature is fully implemented. One scope difference from the plan: the `GET /api/document` endpoint returns the **full document body** (XBRL preamble and Table of Contents stripped, but the full remaining text), not just the requested section. The `section` parameter is used only to resolve section metadata (`section_id`, `section_name`) for the panel header. This was a deliberate implementation choice — the full body is returned so the user can scroll the complete filing and see all highlighted chunks in context, not just those within a single section.

---

## Overview

Add a **"Show document"** button to the `CitationPanel` header. Clicking it fetches the full
section text from the corpus and expands the panel into a document view, with the retrieved
chunk snippets highlighted in-place so the user can see them in context.

---

## 1. What the User Sees

```
Normal CitationPanel (chunk list):
┌─────────────────────────────────────┐
│ [AAPL] 10-K · 2024-11-01  [Show doc]│  ← header + new button
│ Item 1A                             │
├─────────────────────────────────────┤
│ [1]  snippet…                       │
│ [4]  snippet…                       │
└─────────────────────────────────────┘

After clicking "Show document":
┌─────────────────────────────────────┐
│ [AAPL] 10-K · 2024-11-01  [← Chunks]│  ← button toggles back
│ Item 1A · Risk Factors              │
├─────────────────────────────────────┤
│ (full section text, scrollable)     │
│                                     │
│  …Apple's business is subject to…  │
│ ╔═══════════════════════════════╗   │  ← chunk [1] highlighted
│ ║ …operations may be materially ║   │
│ ║ adversely affected…           ║   │
│ ╚═══════════════════════════════╝   │
│  …As of October 2024…              │
│ ╔═══════════════════════════════╗   │  ← chunk [4] highlighted
│ ║ …cybersecurity incidents…     ║   │
│ ╚═══════════════════════════════╝   │
│  …continued…                       │
└─────────────────────────────────────┘
```

The panel does **not** change width — it stays at `w-96` and switches its body content
between "chunk list" and "document view".

---

## 2. Corpus File Lookup

Corpus files live at `edgar_corpus/` with names like:
```
AAPL_10K_2024Q3_2024-11-01_full.txt
AAPL_10Q_2025Q1_2025-01-31_full.txt
```

The source object already contains `ticker`, `filing_type` (e.g. `"10-K (Annual Report)"`),
and `filing_date` (e.g. `"2024-11-01"`). The `section` field is the section ID as stored in
the chunk DB (e.g. `"Item 1A"`).

**File matching logic:**

```python
def find_corpus_file(ticker: str, filing_type: str, filing_date: str) -> Path | None:
    short_type = filing_type.split()[0]          # "10-K (Annual Report)" → "10-K"
    norm_type  = short_type.replace("-", "")     # "10-K" → "10K"
    for path in CORPUS_DIR.iterdir():
        # filename contains ticker, normalised type, and filing_date
        name = path.name
        if (ticker in name
                and norm_type in name
                and filing_date in name
                and name.endswith("_full.txt")):
            return path
    return None
```

**Section extraction logic:**

The corpus files are plain text with sections split by `Item N.` headers (as parsed in
`src/pipeline/chunk.py` with `_SECTION_SPLIT_RE`). Re-use the existing
`split_into_sections()` function to locate the requested section by ID and return its text.

---

## 3. Backend — New Endpoint

`GET /api/document`

Query parameters:
- `ticker` — e.g. `AAPL`
- `filing_type` — e.g. `10-K (Annual Report)` or `10-K`
- `filing_date` — e.g. `2024-11-01`
- `section` — section ID as stored in chunk DB, e.g. `Item 1A`

Response:
```json
{
  "ticker":       "AAPL",
  "filing_type":  "10-K",
  "filing_date":  "2024-11-01",
  "section_id":   "Item 1A",
  "section_name": "Risk Factors",
  "text":         "…full section text…"
}
```

Error cases:
- `404` if no matching corpus file is found
- `404` if the requested section does not exist in the file

**Implementation:**
- New function `get_section_text(ticker, filing_type, filing_date, section_id)` in
  `api/document.py`, using `find_corpus_file()` + `split_into_sections()` from
  `src/pipeline/chunk.py`
- The endpoint is read-only and requires auth (`get_current_user`) for consistency,
  but does not enforce ticker-level RBAC (the user already retrieved the chunk, so
  the filing is within their allowed corpus)
- Add to the existing `/api` Vite proxy (no new proxy entry needed)

---

## 4. Chunk Highlighting in Document Text

Once the section text arrives, the frontend highlights the retrieved snippet substrings
within it.

**Algorithm:**

```ts
function highlightChunks(text: string, snippets: { index: number; text: string }[]) {
  // For each snippet, find its position in the full text (substring search).
  // Build a list of non-overlapping [start, end, chunkIndex] ranges, sorted by start.
  // Split the full text into alternating plain / highlighted segments.
  // Render highlighted segments with a coloured background + citation badge.
}
```

Snippets are stored truncated at 400 chars in the DB (`source.snippet`). The search uses
the snippet text as-is, since it's a direct substring of the original section text.

If a snippet is not found (e.g. due to truncation mismatch), skip it silently — the
chunk card in the list view is still available as fallback.

**Visual treatment for highlighted ranges:**
- Background: `bg-pink-50 dark:bg-pink-950/30`
- Left border: `border-l-2 border-pink-400`
- Small citation badge `[n]` at the top-left of the highlight

---

## 5. Frontend — `CitationPanel` Changes

### State additions

```ts
type PanelView = "chunks" | "document";

const [view,       setView]       = useState<PanelView>("chunks");
const [docText,    setDocText]    = useState<string | null>(null);
const [docLoading, setDocLoading] = useState(false);
const [docError,   setDocError]   = useState<string | null>(null);
```

### "Show document" button

Appears in the panel header next to the existing title. While loading, shows a spinner.
Once loaded, toggles to "← Chunks" to go back.

```tsx
<button onClick={handleToggleView} disabled={docLoading}>
  {view === "document"
    ? "← Chunks"
    : docLoading ? <Spinner /> : "Show document"
  }
</button>
```

### Document view body

Replaces the chunk card list when `view === "document"`:
- Full section text rendered with highlighted snippet ranges
- Each highlight has a small `[n]` badge that, when clicked, scrolls to the matching
  chunk card (switching back to chunk view, or scrolling within the document view itself)
- Auto-scrolls to the first highlighted chunk on load

### Data flow

```
User clicks "Show document"
  → setDocLoading(true), setView("document")
  → fetch GET /api/document?ticker=...&filing_type=...&filing_date=...&section=...
  → setDocText(response.text), setDocLoading(false)
  → render document view with highlights computed from sources[].snippet
```

The fetch result is cached in component state — clicking "← Chunks" and back does not
re-fetch.

---

## 6. API helper (`api.ts`)

```ts
export interface DocumentResponse {
  ticker:       string;
  filing_type:  string;
  filing_date:  string;
  section_id:   string;
  section_name: string;
  text:         string;
}

export async function getDocument(
  ticker:      string,
  filing_type: string,
  filing_date: string,
  section:     string,
): Promise<DocumentResponse>
```

---

## 7. File Changelist

| File | Change |
|---|---|
| `api/document.py` | **New** — `find_corpus_file()`, `get_section_text()`, `GET /api/document` endpoint |
| `api/main.py` | Import + include document router |
| `frontend/src/api.ts` | Add `getDocument()` helper |
| `frontend/src/components/CitationPanel.tsx` | Add view toggle state, "Show document" button, document view with snippet highlighting |

No changes needed to `SourceFooter`, `AnswerPanel`, `App.tsx`, or `ChatSession.tsx`.

---

## 8. Scope Limits

- **Section only, not full filing**: shows just the requested section (e.g. Item 1A), not
  the entire 10-K. Full filings can be tens of thousands of words and would be unusable
  in a side panel.
- **No PDF rendering**: the corpus files are plain text; no PDF viewer is needed.
- **No external link**: the document viewer shows corpus text only. The SEC EDGAR URL is
  available in the file header but we are not linking out.
- **No RBAC enforcement on document fetch**: the user already retrieved chunks from the
  filing via the normal RAG flow, implying the filing is within their allowed corpus.
  Adding a second ticker check would be redundant for this POC.
