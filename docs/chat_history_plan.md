# Chat History — Design & Implementation Plan

## Overview

Every completed query (question + answer + retrieved chunks) is saved to SQLite, keyed on the
authenticated user.  The feature surfaces in two places:

1. **Sidebar** — 5 most recent chats as quick-access links, above the user/logout footer.
2. **History page** — full paginated list; clicking any entry opens a read-only conversation view.

---

## 1. Database Schema

New table in `data/users.db` (same file as the `users` table, managed by `api/history.py`):

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,          -- first ~60 chars of question
    question     TEXT    NOT NULL,
    answer       TEXT    NOT NULL,
    model        TEXT    NOT NULL,
    sources      TEXT    NOT NULL DEFAULT '[]',   -- JSON array of source objects
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conv_user_created
    ON conversations(user_id, created_at DESC);
```

`sources` stores the same shape as the `/api/ask` response sources array:
```json
[
  { "index": 1, "ticker": "AAPL", "filing_type": "10-K",
    "filing_date": "2024-01-26", "section": "risk_factors", "snippet": "..." }
]
```

---

## 2. Backend — `api/history.py`

New module, mirrors the pattern of `api/users.py`.

### 2a. Data access functions

```python
def init_history_db() -> None          # CREATE TABLE IF NOT EXISTS
def save_conversation(user_id, title, question, answer, model, sources) -> int  # returns id
def get_conversations(user_id, limit=50, offset=0) -> list[ConversationRow]
def get_conversation(conv_id, user_id) -> ConversationRow | None  # ownership check
def delete_conversation(conv_id, user_id) -> None                 # ownership check
```

### 2b. API routes — `/history` router (included in `main.py`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/history` | user | List conversations (paginated, newest first). Query params: `limit` (default 20, max 100), `offset`. |
| `GET` | `/history/recent` | user | Return the 5 most-recent conversations (id + title + created_at). Used by sidebar. |
| `GET` | `/history/{id}` | user | Full conversation detail (question, answer, sources). 404 if not owned by caller. |
| `DELETE` | `/history/{id}` | user | Soft-delete (hard DELETE). 404 if not owned by caller. |

Response shapes:

```ts
// GET /history  &  GET /history/recent
{ items: ConversationSummary[], total: number }

interface ConversationSummary {
  id: number; title: string; model: string; created_at: string;
}

// GET /history/{id}
interface ConversationDetail extends ConversationSummary {
  question: string; answer: string; sources: Source[];
}
```

---

## 3. Save Point in Streaming (`api/main.py`)

The `generate()` coroutine in `/api/ask/stream` currently yields events and exits.
After the `event is None` sentinel, we have the complete answer text and sources in memory.

**Changes to `generate()`:**

```python
async def generate():
    loop  = asyncio.get_event_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    accumulated_text   = []
    accumulated_sources = []

    def run_sync():
        ...  # unchanged

    loop.run_in_executor(_stream_executor, run_sync)

    while True:
        event = await queue.get()
        if event is None:
            # ── Save to history ───────────────────────────────
            answer_text = "".join(accumulated_text)
            if answer_text:        # only save if something was generated
                title = req.question[:60].rstrip()
                save_conversation(
                    user_id = user.user_id,
                    title   = title,
                    question = req.question,
                    answer   = answer_text,
                    model    = req.model,
                    sources  = json.dumps(accumulated_sources),
                )
            break
        if event["type"] == "chunk":
            accumulated_text.append(event["text"])
        elif event["type"] == "sources":
            accumulated_sources = event["sources"]
        yield f"data: {json.dumps(event)}\n\n"
```

**Changes to `/api/ask` (sync endpoint):**

After `engine.answer()` returns, call `save_conversation()` with the same fields.

---

## 4. Frontend

### 4a. Types (`frontend/src/types.ts`)

```ts
export interface ConversationSummary {
  id: number;
  title: string;
  model: string;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  question: string;
  answer: string;
  sources: Source[];
}
```

### 4b. API helpers (`frontend/src/api.ts`)

```ts
export async function getHistory(limit = 20, offset = 0): Promise<{ items: ConversationSummary[]; total: number }>
export async function getRecentHistory(): Promise<{ items: ConversationSummary[] }>
export async function getConversation(id: number): Promise<ConversationDetail>
export async function deleteConversation(id: number): Promise<void>
```

### 4c. New page type

`type Page = "chat" | "about" | "settings" | "admin" | "history"`

Add **History** nav item to `Sidebar.tsx` (between Chat and About, non-admin).

### 4d. `HistoryPage` (`frontend/src/pages/HistoryPage.tsx`)

Layout:
- Title "Chat history" + subtitle showing total count.
- Paginated list of `ConversationSummary` cards (20 per page).
- Each card shows: title (truncated), model badge, relative timestamp.
- Clicking a card fetches the full `ConversationDetail` and renders it inline below the card (accordion) or in a modal — **accordion** is simpler and avoids losing list position.
- Inside the expanded accordion: question in a highlighted box, answer rendered with the same `<AnswerPanel>` component, sources rendered with the same `<SourceList>` component (read-only, no new query).
- Delete icon (🗑) per row — shows a confirmation prompt before calling `deleteConversation`.

### 4e. Sidebar recent chats (`frontend/src/components/Sidebar.tsx`)

Insert a section between `<nav>` and the user/logout footer:

```tsx
{/* Recent chats */}
{recentChats.length > 0 && (
  <div className="px-2 pb-2 border-b border-gray-200 dark:border-slate-800">
    <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider
                  text-gray-400 dark:text-slate-500">
      Recent
    </p>
    {recentChats.map((c) => (
      <button key={c.id}
        onClick={() => { onNavigate("history"); onSelectChat(c.id); onClose(); }}
        className="w-full text-left px-3 py-1.5 rounded-lg text-xs
                   text-gray-600 dark:text-slate-400
                   hover:bg-gray-100 dark:hover:bg-slate-800
                   hover:text-gray-900 dark:hover:text-slate-100
                   truncate transition-colors"
        title={c.title}
      >
        {c.title}
      </button>
    ))}
  </div>
)}
```

`recentChats` is fetched from `GET /history/recent` inside `Sidebar` via a `useEffect` that
re-runs whenever `open` becomes `true` (so it refreshes each time the sidebar is opened).

`onSelectChat(id)` is a new optional prop threaded from `App.tsx` — when provided, the
`HistoryPage` opens with that conversation pre-expanded.

---

## 5. App-level wiring (`App.tsx`)

```tsx
const [activeChatId, setActiveChatId] = useState<number | null>(null);

// pass activeChatId to HistoryPage
// clear activeChatId after HistoryPage mounts (useEffect in HistoryPage)

// Sidebar gains:
//   onSelectChat={setActiveChatId}
```

Page rendering:
```tsx
page === "history" ? (
  <HistoryPage activeChatId={activeChatId} onClearActiveChatId={() => setActiveChatId(null)} />
) : ...
```

---

## 6. `init_db` extension (`api/users.py` / `api/main.py`)

`api/history.py` exports its own `init_history_db()`.  Call it alongside `init_db()` at startup
in `main.py`:

```python
from api.history import init_history_db, router as history_router

init_db()
init_history_db()
app.include_router(history_router)
```

Add Vite proxy entry for `/history` (or use existing `/api` prefix — see note below).

> **Prefix decision:** Mount history router at `/api/history` to stay under the existing
> `/api` Vite proxy rule, avoiding a new proxy entry.

---

## 7. File Changelist

| File | Change |
|---|---|
| `api/history.py` | **New** — DB init, CRUD, FastAPI router |
| `api/main.py` | Import + call `init_history_db`, include history router, accumulate text/sources in `generate()`, save on completion for both endpoints |
| `frontend/src/types.ts` | Add `ConversationSummary`, `ConversationDetail` |
| `frontend/src/api.ts` | Add `getHistory`, `getRecentHistory`, `getConversation`, `deleteConversation` |
| `frontend/src/pages/HistoryPage.tsx` | **New** — list + detail view |
| `frontend/src/components/Sidebar.tsx` | Add History nav item, recent-chats section, `onSelectChat` prop |
| `frontend/src/App.tsx` | Add `"history"` to Page type, `activeChatId` state, wire HistoryPage |

---

## 8. UX Flow Summary

```
User submits query
    → answer streams in
    → on stream complete: backend saves conversation to SQLite
    → sidebar "Recent" section refreshes on next open (shows new entry at top)

User opens History page
    → sees paginated list of all past chats
    → clicks a card → accordion expands with full Q&A + sources
    → can delete individual conversations

User clicks a recent chat in sidebar
    → navigated to History page
    → that conversation is pre-expanded
```

---

## 9. What We Are NOT Doing (scope limit)

- No session grouping (every Q&A is a standalone conversation, not a multi-turn thread).
- No full-text search over history (too complex for a POC; add later if needed).
- No export / download of history.
- No admin view of other users' history.
