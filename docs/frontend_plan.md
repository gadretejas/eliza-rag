## Status: Implemented

The frontend described in this plan has been built and significantly extended beyond the original scope. The light Eliza-style theme (see `docs/design.md`) replaced the dark theme. Additional components and pages were added: `CitationPanel.tsx` (right-side slide-in citation panel), `SourceFooter.tsx` (compact source display replacing always-visible source cards), `FollowUpButton.tsx`, `ChatSession.tsx` (multi-turn follow-up interface), `ContextBar.tsx` (token usage progress bar), `Sidebar.tsx` (navigation), `SettingsPage.tsx` (custom LLM endpoint), `ThemeToggle.tsx`, `ProtectedRoute.tsx`, and `AboutDataPage.tsx`. Pages are in `frontend/src/pages/`: `LoginPage.tsx`, `HistoryPage.tsx`, `AdminPage.tsx`. Auth is required for all query endpoints (JWT). The API contract below is the original plan; current endpoints and types are in `frontend/src/api.ts` and `frontend/src/types.ts`.

---

# Frontend Plan — SEC EDGAR RAG

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | React + Vite | Simpler than Next.js; no SSR needed since we have a FastAPI backend |
| Language | TypeScript | Type-safe API contract, better IDE support |
| Styling | Tailwind CSS | Utility-first, fast to iterate, no CSS files to manage |
| Component library | shadcn/ui | Unstyled accessible primitives on top of Tailwind; copy-paste, no runtime overhead |
| State | React useState / useRef | No global state needed — single-page, single query flow |
| HTTP | fetch (native) | No extra dependency; simple POST to /api/ask |

---

## Design Language

**Tone:** Professional financial tool — not a chatbot. Clean, dense, data-forward.

**Palette:**
- Background: `slate-950` (near-black)
- Surface: `slate-900`
- Border: `slate-700`
- Primary accent: `blue-500` (citation highlights, buttons)
- Text: `slate-100` (primary), `slate-400` (secondary/metadata)
- Ticker badges: company-colour accents or neutral `slate-700` pills

**Typography:**
- UI: Inter or system-ui
- Answer body: slightly larger, comfortable reading size (16–17px), line-height 1.7
- Source snippets: monospace or smaller sans, `slate-300`

**Layout:** Single-column centred, max-width 860px. No sidebar.

---

## Page Structure

```
┌─────────────────────────────────────────────────────────┐
│  Header — "SEC EDGAR Research"           [model picker] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Question input (textarea, auto-resize)         │   │
│  │                                          [Ask →] │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ── Answer ─────────────────────────────────────────   │
│  Answer text with inline [1] [2] citation chips        │
│  (clickable → scrolls to / highlights source card)     │
│                                                         │
│  ── Sources ────────────────────────────────────────   │
│  [1] AAPL · 10-K · 2025-10-31 · Item 1A  [▼ expand]  │
│  [2] TSLA · 10-K · 2026-01-29 · Item 1A  [▼ expand]  │
│  ...                                                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### `App.tsx`
Top-level. Holds `question`, `result`, `loading`, `error` state.
Renders Header → QueryBox → (AnswerPanel + SourceList).

### `QueryBox.tsx`
- Auto-resizing textarea
- "Ask" button with loading spinner
- Keyboard shortcut: Cmd/Ctrl+Enter to submit
- Disabled while loading

### `AnswerPanel.tsx`
- Renders `answer_text` with `[n]` markers replaced by `<CitationChip>` components
- Clicking a chip highlights the corresponding source card and scrolls to it
- Shows model used + chunk count as small metadata below the answer

### `CitationChip.tsx`
- Small `[n]` badge, `blue-500` background on hover / active
- `onClick` → calls `onCitationClick(index)` passed down from App

### `SourceList.tsx`
- Renders a `SourceCard` for each source
- Highlighted card (from citation click) gets a `ring-2 ring-blue-500` border

### `SourceCard.tsx`
- Shows: index badge, ticker pill, filing type, filing date, section
- Collapsed by default — click to expand snippet text
- Snippet text is the 400-char passage from the API

### `TickerBadge.tsx`
- Pill with ticker symbol
- Optional: sector-based colour (tech = blue, pharma = green, finance = amber)

### `ModelPicker.tsx`
- Dropdown in header: `gpt-5.4-mini` (default) / `gpt-5.4`
- Sets `model` field in the request body

---

## API Contract (from `api/main.py`)

**Request**
```typescript
POST /api/ask
{
  question: string,
  model: "gpt-5.4-mini" | "gpt-5.4",   // default: gpt-5.4-mini
  top_k: number                          // default: 15
}
```

**Response**
```typescript
{
  answer: string,          // LLM text with [1][2] markers intact
  sources: {
    index:        number,
    ticker:       string,  // "AAPL"
    filing_type:  string,  // "10-K (Annual Report)"
    filing_date:  string,  // "2025-10-31"
    section:      string,  // "Item 1A"
    snippet:      string,  // first 400 chars of passage_text
  }[]
}
```

**One API change needed:** The API currently creates a new `AnswerEngine` on every request.
Move to the lazy-loaded `_get_engine()` singleton so ChromaDB is only opened once.

---

## Citation Rendering — Key Implementation Detail

The answer text contains markers like `"Apple's revenue was $391B [1][4]."`.
These need to become interactive chips without breaking the surrounding prose.

```typescript
function renderAnswerWithCitations(
  text: string,
  onCitationClick: (index: number) => void
): React.ReactNode[] {
  const parts = text.split(/(\[\d+\])/g)
  return parts.map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/)
    if (match) {
      const idx = parseInt(match[1])
      return <CitationChip key={i} index={idx} onClick={() => onCitationClick(idx)} />
    }
    return <span key={i}>{part}</span>
  })
}
```

---

## File Structure

```
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts          # proxy /api → http://localhost:8000
├── tailwind.config.ts
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api.ts              # typed fetch wrapper for /api/ask
    ├── types.ts            # AskRequest, AskResponse, Source
    └── components/
        ├── QueryBox.tsx
        ├── AnswerPanel.tsx
        ├── CitationChip.tsx
        ├── SourceList.tsx
        ├── SourceCard.tsx
        ├── TickerBadge.tsx
        └── ModelPicker.tsx
```

---

## Implementation Order

1. Scaffold with `npm create vite@latest frontend -- --template react-ts`
2. Install Tailwind, configure `vite.config.ts` proxy (`/api` → `localhost:8000`)
3. Define `types.ts` and `api.ts`
4. Build `QueryBox` + wire to API — get a raw JSON response rendering first
5. Build `AnswerPanel` with citation regex split
6. Build `SourceCard` + `SourceList` with expand/collapse
7. Wire citation click → source highlight + scroll
8. Add `ModelPicker`, `TickerBadge`, loading/error states
9. Polish: keyboard shortcut, empty state, dark theme

---

## States to Handle

| State | UI |
|---|---|
| Empty (initial) | Centered input, example questions below it |
| Loading | Input disabled, spinner on button, skeleton answer area |
| Success | Answer + sources rendered |
| Error (API down) | Red banner: "Could not reach the API" |
| Error (empty question) | Inline validation on the input |

---

## One-liner to start the full stack locally

```bash
# Terminal 1 — API
uvicorn api.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev        # Vite dev server on :5173, proxies /api to :8000
```
