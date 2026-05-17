# Follow-up Chat — Design & Implementation Plan

## Overview

After receiving a single-turn Q&A answer, the user can click **"Follow up"** to enter a
persistent chat session.  The session accumulates conversation history and tracks token usage
against the selected model's context window, showing a live progress bar, a yellow warning at
90%, and disabling the input at 100%.

---

## 1. Core Concepts

### 1a. Retrieval strategy

Every turn (including follow-ups) runs a fresh retrieval against the corpus using the **new
user message as the query**.  The retrieved chunks are injected into the prompt alongside the
conversation history.  This keeps every answer grounded in filings while letting the LLM use
prior turns for continuity.

```
Turn N prompt structure
─────────────────────────────────────────────
[System prompt]
[Retrieved chunks for turn-N question]     ← re-retrieved each turn
[Message history: turns 1 … N-1]          ← full prior dialogue
[User: turn-N question]
```

### 1b. Token accounting

The backend counts tokens for every message using `tiktoken` (OpenAI models) or a
character-based estimate (`len(text) // 4`) for Anthropic/local models.  It returns
`tokens_used` and `context_limit` in every stream response.  The frontend renders this
directly — no client-side counting.

### 1c. Model context windows

```python
CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.4-mini":      128_000,
    "gpt-5.4":           128_000,
    "claude-haiku-4-5":  200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-opus-4-5":   200_000,
}
DEFAULT_CONTEXT_WINDOW = 8_192   # safe fallback for unknown/custom models
```

Custom models (user-supplied API key + model name) use `DEFAULT_CONTEXT_WINDOW` unless
overridden.

---

## 2. Database Schema

New tables in `data/users.db`, managed by `api/sessions.py`.

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,          -- first question truncated to 60 chars
    model      TEXT    NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS session_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
    content     TEXT    NOT NULL,
    sources     TEXT    NOT NULL DEFAULT '[]',   -- JSON, empty for user turns
    tokens      INTEGER NOT NULL DEFAULT 0,      -- tokens in this message
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sess_user   ON sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sess_msg    ON session_messages(session_id, created_at ASC);
```

**Relationship to `conversations`:** Single-turn Q&As remain in the `conversations` table.
A follow-up session is a separate entity — the original Q&A is copied into the session as the
first two messages (user + assistant) when the session is created.

---

## 3. Backend

### 3a. New module `api/sessions.py`

**Data access helpers:**

```python
def init_sessions_db() -> None
def create_session(user_id, title, model) -> int           # returns session id
def append_message(session_id, role, content, sources, tokens) -> int
def get_session(session_id, user_id) -> SessionRow | None  # ownership check
def get_messages(session_id) -> list[MessageRow]
def list_sessions(user_id, limit, offset) -> tuple[list[SessionRow], int]
def delete_session(session_id, user_id) -> bool
def count_session_tokens(session_id) -> int               # sum of all message tokens
```

**API router** (prefix `/api/sessions`):

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/sessions` | Create session from an existing single-turn Q&A (pass `conv_id`) or blank. Returns `{ session_id, context_limit }`. |
| `GET` | `/api/sessions` | Paginated list of sessions (summary: id, title, model, created_at). |
| `GET` | `/api/sessions/{id}` | Full session: messages + `tokens_used` + `context_limit`. |
| `POST` | `/api/sessions/{id}/message` | Send follow-up, stream response (SSE). Body: `{ question, top_k? }`. |
| `DELETE` | `/api/sessions/{id}` | Delete session. |

### 3b. New method `AnswerEngine.followup_stream()`

Extend `src/answer/answer.py` with:

```python
def followup_stream(
    self,
    history: list[dict],   # [{"role": "user"|"assistant", "content": "..."}]
    question: str,
) -> Iterator[dict]:
```

Yields the same SSE event types as `answer_stream`, plus two new ones:

```json
{ "type": "token_count", "tokens_used": 4210, "context_limit": 128000 }
```

emitted once after the `sources` event (before the first `chunk`), and again after `done`.

**Implementation inside `followup_stream`:**

1. Retrieve chunks for `question` (same as `answer_stream`).
2. Build a multi-turn messages array:
   - `system`: system prompt + chunk context (same as single-turn)
   - Then inject `history` messages as alternating user/assistant turns
   - Finally append the new user message
3. Call `llm.stream_messages(messages, ...)` — requires a small addition to `LLMClient`
   (OpenAI and Anthropic both natively support message arrays).
4. Count tokens via `tiktoken` or character estimate.
5. Yield `token_count` event before first chunk and after `done`.

### 3c. Streaming endpoint `POST /api/sessions/{id}/message`

```python
@sessions_router.post("/{session_id}/message")
async def send_message(session_id, req, user) -> StreamingResponse:
    # 1. Ownership check
    # 2. check_rate_limit, check_model_access
    # 3. Load message history from DB
    # 4. Check tokens_used < context_limit (hard reject if over)
    # 5. engine.followup_stream(history, req.question)
    # 6. Accumulate + save user message + assistant message to DB
    # 7. Stream SSE back
```

**Hard reject response** when at or over the context limit:
```json
{ "detail": "Context limit reached. Start a new chat." }
```
HTTP 422.

### 3d. Token counting helper

```python
# api/token_count.py

CONTEXT_WINDOWS = { "gpt-5.4-mini": 128_000, ... }
DEFAULT_CONTEXT_WINDOW = 8_192

def get_context_limit(model: str) -> int: ...

def count_tokens(text: str, model: str) -> int:
    """tiktoken for OpenAI models, char//4 fallback for others."""
```

---

## 4. Frontend

### 4a. New types (`types.ts`)

```ts
export interface SessionMessage {
  id:         number;
  role:       "user" | "assistant";
  content:    string;
  sources:    Source[];
  tokens:     number;
  created_at: string;
}

export interface ChatSession {
  id:            number;
  title:         string;
  model:         string;
  messages:      SessionMessage[];
  tokens_used:   number;
  context_limit: number;
  created_at:    string;
}
```

### 4b. New API helpers (`api.ts`)

```ts
createSession(convId?: number, model?: string): Promise<{ session_id: number; context_limit: number }>
getSession(id: number): Promise<ChatSession>
sendFollowUp(sessionId: number, question: string, callbacks, signal?): Promise<void>
listSessions(limit, offset): Promise<{ items: SessionSummary[]; total: number }>
deleteSession(id: number): Promise<void>
```

`sendFollowUp` is an SSE stream identical to `streamQuestion` but also handles the new
`token_count` event type.

### 4c. New components

**`ContextBar.tsx`**

A thin progress bar + label shown at the top of the chat session view.

```
▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░  4,210 / 128,000 tokens (3%)
```

| Usage | Bar colour | Banner |
|---|---|---|
| < 90% | green | none |
| 90–99% | amber | "Approaching context limit — start a new chat soon" |
| 100% | red (full) | "Context limit reached. No more messages can be sent." |

**`FollowUpButton.tsx`**

Simple pill button rendered below the `AnswerPanel` once `done === true && !error`:

```tsx
<button onClick={onFollowUp}
  className="px-4 py-1.5 rounded-full text-sm font-medium border
             border-pink-300 text-pink-600 hover:bg-pink-50 ...">
  Follow up ↩
</button>
```

**`ChatSession.tsx`**

Replaces the current answer/sources view when a session is active.  Layout:

```
┌──────────────────────────────────────────────────┐
│ ContextBar  (tokens / limit, coloured bar)       │
├──────────────────────────────────────────────────┤
│  [scroll area]                                   │
│  User bubble: original question                  │
│  Assistant: AnswerPanel + SourceList (read-only) │
│  ─────────────────────────────────────────       │
│  User bubble: follow-up 1                        │
│  Assistant: AnswerPanel + SourceList             │
│  ...                                             │
├──────────────────────────────────────────────────┤
│ QueryBox (disabled when 100% or streaming)       │
│ [Send]                                           │
└──────────────────────────────────────────────────┘
```

- Each assistant turn renders `AnswerPanel` + `SourceList` (same components, read-only when not
  the latest turn).
- The latest assistant turn streams in live (identical to the current single-turn flow).
- Auto-scroll to bottom on each new token.
- A small "← Back to new chat" link in the top-left exits the session without deleting it.

### 4d. App.tsx changes

Add state:

```ts
const [activeSession, setActiveSession] = useState<{
  id: number;
  contextLimit: number;
} | null>(null);
```

**Entry flow:**

1. `done === true && !error && !activeSession` → show `<FollowUpButton>` below the answer.
2. User clicks → call `createSession(convId)` → set `activeSession`.
3. Render `<ChatSession sessionId={activeSession.id} ... />` instead of the current
   answer/sources stack.
4. "← Back to new chat" clears `activeSession` and resets the query box.

Sessions are also accessible from the History page (sessions listed alongside single-turn
conversations, visually distinguished with a chat-bubble icon vs a single-turn icon).

---

## 5. `LLMClient` additions (`src/answer/answer.py`)

Add `stream_messages()` alongside the existing `stream()`:

```python
def stream_messages(
    self,
    messages: list[dict],   # [{"role": "system"|"user"|"assistant", "content": "..."}]
    temperature: float = 0.2,
    max_tokens:  int   = 1024,
) -> Iterator[str]:
```

OpenAI and Anthropic both accept a `messages` array natively — this is a thin wrapper around
the existing call pattern.

---

## 6. File Changelist

| File | Change |
|---|---|
| `api/sessions.py` | **New** — DB init, CRUD, `/api/sessions` router |
| `api/token_count.py` | **New** — context window map, tiktoken helper |
| `api/main.py` | Import + call `init_sessions_db`, include sessions router |
| `src/answer/answer.py` | Add `LLMClient.stream_messages()`, `AnswerEngine.followup_stream()` |
| `frontend/src/types.ts` | Add `SessionMessage`, `ChatSession`, `SessionSummary` |
| `frontend/src/api.ts` | Add session API helpers |
| `frontend/src/components/ContextBar.tsx` | **New** — token usage progress bar |
| `frontend/src/components/FollowUpButton.tsx` | **New** — entry-point button |
| `frontend/src/components/ChatSession.tsx` | **New** — multi-turn chat view |
| `frontend/src/App.tsx` | `activeSession` state, wire FollowUpButton → ChatSession |

---

## 7. UX Flow Summary

```
Single-turn answer completes
  → "Follow up ↩" button appears

User clicks Follow up
  → POST /api/sessions  (copies original Q&A as first two messages)
  → UI transitions to ChatSession view
  → ContextBar shows baseline token usage

User types follow-up question → sends
  → POST /api/sessions/{id}/message  (SSE stream)
  → Retrieval runs for new question
  → LLM sees chunks + full history + new question
  → Tokens accumulate; ContextBar updates on token_count events

At 90%
  → ContextBar turns amber
  → Warning banner: "Approaching context limit — start a new chat soon"

At 100%
  → ContextBar turns red
  → Input box disabled
  → Banner: "Context limit reached. No more messages can be sent."
  → Backend hard-rejects any further messages with HTTP 422
```

---

## 8. What We Are NOT Doing (scope limit)

- No session branching (can't fork a conversation at a specific turn).
- No context pruning / summarisation (we disable rather than truncate).
- No cross-session search.
- Sessions are not shown in the sidebar Recent section (only single-turn Q&As appear there).
