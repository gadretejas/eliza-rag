# Admin Dashboard — Token Usage by Model per User

## Overview

Add a **Dashboard** tab to the existing `AdminPage` (visible to admins only) that shows
token consumption broken down by user and model. Token usage is logged to a new SQLite
table on every LLM call and aggregated on-demand via a new admin endpoint.

---

## 1. What the Admin Sees

```
Admin page
┌──────────────────────────────────────────────────────┐
│  [Users]  [Dashboard]                                │  ← tab bar
└──────────────────────────────────────────────────────┘

Dashboard tab:
┌──────────────────────────────────────────────────────┐
│  Summary cards                                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│  │ 1.2M tokens  │ │  47 calls    │ │  3 users     │ │
│  │ Total        │ │ Total calls  │ │ Active       │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ │
│                                                      │
│  Usage by user                                       │
│  ┌──────────────────────────────────────────────┐    │
│  │ User            │ gpt-5.4-mini │ gpt-5.4 │ Total │
│  │─────────────────────────────────────────────│    │
│  │ alice@example   │    850 K     │  12 K   │ 862 K │
│  │ bob@example     │    310 K     │   —     │ 310 K │
│  │─────────────────────────────────────────────│    │
│  │ Total           │  1,160 K     │  12 K   │ 1.2 M │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

- Tokens are displayed human-formatted: `1,234`, `12 K`, `1.2 M`
- Zero cells show `—` instead of 0
- Total row at bottom, total column at right
- Summary cards above the table

---

## 2. Token Logging

### New table: `token_usage`

```sql
CREATE TABLE IF NOT EXISTS token_usage (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    user_email       TEXT    NOT NULL,
    model            TEXT    NOT NULL,
    endpoint         TEXT    NOT NULL,   -- 'ask' | 'ask/stream' | 'session/message'
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tu_user  ON token_usage(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tu_model ON token_usage(model, created_at DESC);
```

### What counts as tokens

| Field | How measured |
|---|---|
| `prompt_tokens` | `count_tokens(question, model)` — question text sent to the model |
| `completion_tokens` | `count_tokens(answer_text, model)` — streamed/returned answer |
| `total_tokens` | `prompt_tokens + completion_tokens` |

This is a deliberate approximation: the full prompt also includes the system prompt and
retrieved context, but those are not trivially available at the logging site. The question
+ answer pair captures the user-attributable usage and is consistent across all three
endpoints.

### Where to log

| Endpoint | When | File |
|---|---|---|
| `POST /api/ask` | After `engine.answer()` returns | `api/main.py` |
| `POST /api/ask/stream` | In `generate()` when `event["type"] == "done"`, after saving the conversation | `api/main.py` |
| `POST /api/sessions/{id}/message` | In `generate()` after the `None` sentinel, after saving messages | `api/sessions.py` |

---

## 3. Backend

### New file: `api/token_usage.py`

```python
def init_token_usage_db() -> None: ...

def log_token_usage(
    user_id:          int,
    user_email:       str,
    model:            str,
    endpoint:         str,
    prompt_tokens:    int,
    completion_tokens: int,
) -> None: ...

def get_usage_stats() -> dict:
    """
    Returns aggregated token usage for the admin dashboard.
    Shape:
    {
      "users": [
        {
          "user_id":     1,
          "email":       "alice@example.com",
          "total":       862_000,
          "by_model":    { "gpt-5.4-mini": 850_000, "gpt-5.4": 12_000 },
          "call_count":  45,
        },
        ...
      ],
      "models":       ["gpt-5.4-mini", "gpt-5.4"],   # all distinct models, sorted
      "grand_total":  1_172_000,
      "total_calls":  47,
    }
    """
```

### New admin endpoint: `GET /admin/token-usage`

Added to `admin_router` in `api/main.py`:

```python
@admin_router.get("/token-usage")
def admin_token_usage(
    _: TokenClaims = Depends(require_admin),
) -> dict:
    return get_usage_stats()
```

No query parameters for v1 — always returns all-time totals.

### Startup

`init_token_usage_db()` called in `api/main.py` alongside the other `init_*` calls.

---

## 4. Frontend

### Tab bar in `AdminPage.tsx`

```tsx
type Tab = "users" | "dashboard";
const [tab, setTab] = useState<Tab>("users");
```

A two-tab pill bar replaces the current plain heading. The existing user management UI
renders when `tab === "users"`; the new dashboard renders when `tab === "dashboard"`.

### Dashboard component (inline in `AdminPage.tsx`)

State:

```tsx
const [stats,      setStats]      = useState<UsageStats | null>(null);
const [statsLoading, setStatsLoading] = useState(false);
const [statsError,   setStatsError]   = useState<string | null>(null);
```

Loaded on mount (or when tab switches to "dashboard"). Displays:

1. **Summary cards row** — Total tokens / Total calls / Unique users
2. **Usage table** — rows = users sorted by total desc, columns = distinct models + Total column

### New API types (`frontend/src/types.ts`)

```ts
export interface UserUsage {
  user_id:    number;
  email:      string;
  total:      number;
  by_model:   Record<string, number>;
  call_count: number;
}

export interface UsageStats {
  users:       UserUsage[];
  models:      string[];
  grand_total: number;
  total_calls: number;
}
```

### New API helper (`frontend/src/api.ts`)

```ts
export async function adminGetTokenUsage(): Promise<UsageStats> {
  const res = await fetch("/admin/token-usage", { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to load usage stats (${res.status})`);
  return res.json();
}
```

### Token formatting helper

```ts
function fmtTokens(n: number): string {
  if (n === 0)         return "—";
  if (n >= 1_000_000)  return `${(n / 1_000_000).toFixed(1)} M`;
  if (n >= 1_000)      return `${(n / 1_000).toFixed(0)} K`;
  return n.toLocaleString();
}
```

---

## 5. File Changelist

| File | Change |
|---|---|
| `api/token_usage.py` | **New** — `init_token_usage_db()`, `log_token_usage()`, `get_usage_stats()` |
| `api/main.py` | Import + call `init_token_usage_db()`; add `GET /admin/token-usage`; call `log_token_usage()` after `POST /api/ask` and `POST /api/ask/stream` |
| `api/sessions.py` | Call `log_token_usage()` after follow-up message completes |
| `frontend/src/types.ts` | Add `UserUsage`, `UsageStats` interfaces |
| `frontend/src/api.ts` | Add `adminGetTokenUsage()` |
| `frontend/src/pages/AdminPage.tsx` | Add tab bar, Dashboard tab with summary cards + usage table |

No changes needed to `auth.py`, `permissions.py`, `history.py`, `document.py`, or any
component outside `AdminPage.tsx`.

---

## 6. Scope Limits

- **All-time only (v1)**: no date range filter; always aggregates the full `token_usage`
  table. A date picker can be added later by passing `?since=YYYY-MM-DD` to the endpoint.
- **Approximate prompt tokens**: only the question text is counted for `prompt_tokens`,
  not the full system prompt + retrieved context. This is consistent and sufficient for
  relative usage comparisons.
- **No cost calculation**: token costs vary by model and Anthropic/OpenAI pricing changes
  frequently. The table shows raw token counts only; cost estimation is out of scope.
- **No per-session breakdown**: aggregated totals only. Per-conversation drill-down is a
  future enhancement.
