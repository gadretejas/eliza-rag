# Citation Panel UX Redesign — Plan

## Overview

Replace the always-visible source card list below the answer with two things:
1. A compact **deduplicated file chip list** (`SourceFooter`) — one chip per unique source file
2. A **slide-in right panel** (`CitationPanel`) — opens when the user clicks a citation number
   `[n]` in the answer text or a chip in the footer

The `HistoryPage` accordion is unaffected and keeps the existing `SourceList` / `SourceCard`
components.

---

## 1. What Changes

| Current | New |
|---|---|
| All `SourceCard` cards rendered below the answer at all times | Replaced by `SourceFooter` — compact deduplicated chips |
| Clicking `[n]` highlights + scrolls to the matching card | Clicking `[n]` opens `CitationPanel` scrolled to that chunk |
| `activeIndex` state inline-highlights the active card | `panel` state drives the panel open/close/focus |
| `SourceList` used in main chat, ChatSession, and HistoryPage | `SourceList` kept only for HistoryPage; replaced elsewhere |

---

## 2. `SourceFooter` (new component)

Sits directly below the answer text. Shows one chip per unique
`(ticker, filing_type, filing_date, section)` combination — no matter how many chunks
came from the same file, only one chip appears.

**Visual:**
```
Sources   [AAPL] 10-K · 2024-11-01 · risk_factors   [AAPL] 10-Q · 2025-01-31 · risk_factors
```

Each chip contains:
- `TickerBadge` for the ticker (colour-coded by sector)
- filing type, filing date, section in muted text

Clicking a chip opens `CitationPanel` showing all chunks from that file, with no specific
chunk pre-focused.

**Deduplication logic:**
```ts
const uniqueFiles = sources.reduce((acc, s) => {
  const key = `${s.ticker}|${s.filing_type}|${s.filing_date}|${s.section}`;
  if (!acc.has(key)) acc.set(key, s);
  return acc;
}, new Map<string, Source>());
```

---

## 3. `CitationPanel` (new component)

A fixed right-side slide-in panel. Does not push page content — overlays it.

**Dimensions:** `w-96` (384 px), full viewport height, `fixed top-0 right-0 z-50`.

**Triggered by:**
- Clicking `[n]` in the answer → opens panel, scrolls to chunk `n`, highlights it
- Clicking a `SourceFooter` chip → opens panel showing all chunks from that file, no highlight

**Panel layout:**
```
┌──────────────────────────────────────┐
│ [✕]  AAPL · 10-K · 2024-11-01       │  ← sticky header
│      risk_factors                    │
├──────────────────────────────────────┤
│  [1]                                 │  ← chunk cards, scrollable
│  snippet text for chunk 1…           │
│  ──────────────────────────────────  │
│  [4]  ← highlighted if focused      │
│  snippet text for chunk 4…           │
│  ──────────────────────────────────  │
│  [7]                                 │
│  snippet text for chunk 7…           │
└──────────────────────────────────────┘
```

**Behaviour:**
- Clicking `[n]` when panel is already open on the same citation → **closes** the panel (toggle)
- Clicking `[n]` when panel is open on a different citation → **stays open**, re-focuses to new chunk
- Clicking `[n]` from a different answer turn → **replaces** panel content with new turn's sources
- Clicking the `✕` button or pressing `Escape` → closes
- Semi-transparent backdrop (`bg-black/20`) on screens narrower than `lg` only; on desktop the
  panel floats over the right side without a backdrop

**Entry animation:** `translate-x-full` → `translate-x-0` with `transition-transform duration-200`.

---

## 4. State Model

Replace `activeIndex: number | null` in `App.tsx` and `ChatSession.tsx` with:

```ts
interface PanelState {
  sources:    Source[];       // all sources for the answer that opened the panel
  focusIndex: number | null;  // citation [n] that was clicked; null = no specific focus
}
const [panel, setPanel] = useState<PanelState | null>(null);
```

`panel === null` → panel closed.
`panel.focusIndex = 3` → panel open, chunk [3] scrolled into view and highlighted.

**Handler:**
```ts
function handleCitationClick(index: number, sources: Source[]) {
  setPanel((prev) => {
    // Same citation clicked again → toggle close
    if (prev && prev.focusIndex === index &&
        prev.sources === sources) return null;
    return { sources, focusIndex: index };
  });
}

function handleFooterChipClick(source: Source, sources: Source[]) {
  // Filter panel to all chunks from this file
  const fileChunks = sources.filter(
    (s) => s.ticker === source.ticker &&
           s.filing_type === source.filing_type &&
           s.filing_date === source.filing_date &&
           s.section === source.section
  );
  setPanel({ sources: fileChunks, focusIndex: null });
}
```

---

## 5. Component Updates

### `CitationChip.tsx`
- Remove the `active` boolean prop and its highlight styling (pink filled state)
- Keep `pending` to disable chips during streaming
- Chip is now always in the same visual state (pink outline) regardless of panel

### `AnswerPanel.tsx`
- Remove `activeIndex` prop
- `onCitationClick(index)` signature stays the same — caller decides what to do with it

### `SourceList.tsx` + `SourceCard.tsx`
- **No changes** — kept exactly as-is for `HistoryPage` accordion

---

## 6. Usage in `App.tsx`

**Before:**
```tsx
<AnswerPanel ... activeIndex={activeIndex} onCitationClick={handleCitationClick} />
<SourceList sources={sources} activeIndex={activeIndex} />
```

**After:**
```tsx
<AnswerPanel ... onCitationClick={(i) => handleCitationClick(i, sources)} />
<SourceFooter sources={sources} onChipClick={(s) => handleFooterChipClick(s, sources)} />

{/* Portal or sibling at root level */}
{panel && (
  <CitationPanel
    sources={panel.sources}
    focusIndex={panel.focusIndex}
    onClose={() => setPanel(null)}
  />
)}
```

---

## 7. Usage in `ChatSession.tsx`

Each assistant turn renders its own `SourceFooter`. The panel state is lifted to the
`ChatSession` level (one panel open at a time across all turns). Opening a citation from
turn 3 closes any panel that was open from turn 1.

```tsx
// In ChatSession top-level state
const [panel, setPanel] = useState<PanelState | null>(null);

// Passed down to each MessageBubble (assistant turns only)
<SourceFooter
  sources={msg.sources}
  onChipClick={(s) => handleFooterChipClick(s, msg.sources)}
/>
<AnswerPanel
  ...
  onCitationClick={(i) => handleCitationClick(i, msg.sources)}
/>

// Rendered once at ChatSession root
{panel && <CitationPanel ... onClose={() => setPanel(null)} />}
```

---

## 8. File Changelist

| File | Change |
|---|---|
| `components/CitationPanel.tsx` | **New** — slide-in panel with per-file chunk list |
| `components/SourceFooter.tsx` | **New** — deduplicated file chip list below answer |
| `components/CitationChip.tsx` | Remove `active` prop and highlight state |
| `components/AnswerPanel.tsx` | Remove `activeIndex` prop |
| `components/SourceList.tsx` | Unchanged — kept for HistoryPage |
| `components/SourceCard.tsx` | Unchanged — reused inside CitationPanel |
| `frontend/src/App.tsx` | Replace `activeIndex` + `SourceList` with `panel` state + `CitationPanel` + `SourceFooter` |
| `components/ChatSession.tsx` | Same swap as App.tsx |

---

## 9. What We Are NOT Doing

- No changes to backend or API — `sources` array shape is unchanged
- No changes to `HistoryPage` — keeps its existing accordion with `SourceList`
- No full-text filing viewer — the panel shows the retrieved snippet only, not the full document
- No pinning or multi-panel (only one panel open at a time)
