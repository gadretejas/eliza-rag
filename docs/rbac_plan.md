# RBAC Implementation Plan

## Current State

The system is entirely open — any caller can query any company, any model, with no identity. There are no users, no sessions, no auth middleware. The FastAPI backend is stateless; the React frontend stores only model preferences in `localStorage`.

---

## What RBAC Controls

For a financial research RAG system the meaningful access dimensions are:

| Dimension | Example restriction |
|---|---|
| **Corpus access** | A viewer can only query Technology + Healthcare companies; an analyst can query all 54 |
| **Model access** | Viewers can only use `gpt-5.4-mini`; analysts can use any model |
| **Rate limiting** | Viewers: 20 questions/hour; analysts: 200/hour; admin: unlimited |
| **User management** | Only admins can create accounts, assign roles, deactivate users |

---

## Roles

Three roles cover all realistic use cases:

| Role | Corpus | Models | Rate limit | User mgmt |
|---|---|---|---|---|
| `admin` | All companies | All | None | Yes |
| `analyst` | All companies | All | 200 req/hr | No |
| `viewer` | Configured sectors only | `gpt-5.4-mini` only | 20 req/hr | No |

Viewer corpus restrictions are configured per-user at account creation (e.g., `allowed_tickers: ["AAPL","MSFT","NVDA"]`).

---

## Architecture

### Auth Strategy: JWT (Stateless)

JWT fits the existing stateless architecture perfectly — no session store needed. Role and allowed tickers are embedded in the token claims so the API enforces permissions without a DB hit on every request.

```
Token claims:
{
  "sub": "user@example.com",
  "role": "analyst",
  "allowed_tickers": "*",          // "*" means all; or ["AAPL","MSFT"]
  "exp": 1234567890
}
```

### User Store: SQLite

Reuse the existing SQLite infrastructure. Add a `users` table alongside the existing data:

```sql
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    UNIQUE NOT NULL,
    hashed_password TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'viewer',
    allowed_tickers TEXT    NOT NULL DEFAULT '*',   -- JSON array or '*'
    is_active       BOOLEAN NOT NULL DEFAULT 1,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## New Files

```
api/
├── main.py              (modified — add auth dependency to /api/ask endpoints)
├── auth.py              (new — JWT creation, validation, login/register endpoints)
├── users.py             (new — user store, CRUD, SQLite ops)
└── permissions.py       (new — role permission definitions, model/ticker checks)
```

---

## Backend Implementation

### `api/auth.py` — Auth endpoints and JWT

```python
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.environ["JWT_SECRET_KEY"]   # add to .env
ALGORITHM  = "HS256"
TOKEN_TTL  = timedelta(hours=8)

pwd_ctx   = CryptContext(schemes=["bcrypt"])
oauth2    = OAuth2PasswordBearer(tokenUrl="/auth/login")
router    = APIRouter(prefix="/auth")

@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_email(form.username)
    if not user or not pwd_ctx.verify(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({
        "sub":             user.email,
        "role":            user.role,
        "allowed_tickers": user.allowed_tickers,
        "exp":             datetime.utcnow() + TOKEN_TTL,
    }, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@router.post("/register")        # admin-only in production
def register(email, password, role, allowed_tickers, current_user=...): ...

@router.get("/me")
def me(current_user = Depends(get_current_user)): ...
```

### `api/permissions.py` — Role enforcement

```python
ALLOWED_MODELS: dict[str, set[str] | str] = {
    "admin":   "*",
    "analyst": "*",
    "viewer":  {"gpt-5.4-mini", "claude-haiku"},
}

RATE_LIMITS: dict[str, int | None] = {   # requests per hour
    "admin":   None,
    "analyst": 200,
    "viewer":  20,
}

def check_model_access(user: TokenClaims, model: str):
    allowed = ALLOWED_MODELS[user.role]
    if allowed != "*" and model not in allowed:
        raise HTTPException(403, f"Role '{user.role}' cannot use model '{model}'")

def get_ticker_filter(user: TokenClaims) -> list[str] | None:
    """Return allowed tickers list, or None meaning unrestricted."""
    if user.allowed_tickers == "*":
        return None
    return json.loads(user.allowed_tickers)
```

### `api/main.py` — Modified endpoints

Add a `get_current_user` dependency to both `/api/ask` endpoints:

```python
from api.auth import get_current_user
from api.permissions import check_model_access, get_ticker_filter

@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest, user=Depends(get_current_user)):
    check_model_access(user, req.model)
    ticker_filter = get_ticker_filter(user)
    engine = _get_engine(req, ticker_filter=ticker_filter)
    ...
```

The `ticker_filter` is passed into `AnswerConfig` → `RetrieverConfig`, which already supports `tickers` filtering in `HybridRetriever`. No changes needed to the retrieval layer — it already knows how to restrict results to a list of tickers.

---

## Frontend Implementation

### New components

```
frontend/src/
├── contexts/AuthContext.tsx     (new — user state, login/logout, JWT storage)
├── pages/LoginPage.tsx          (new — email/password form)
├── components/ProtectedRoute.tsx (new — redirect to login if no token)
```

### Auth flow

1. User submits email + password on `LoginPage`
2. `POST /auth/login` → receive JWT
3. Store JWT in `localStorage` (same pattern as saved models)
4. All subsequent calls to `/api/ask` include `Authorization: Bearer <token>`
5. On 401 response, clear token and redirect to login

### Role-aware UI changes

- `ModelPicker` — filter available models based on role embedded in decoded JWT
- `SettingsPage` — show/hide admin section (user management) based on role
- `Sidebar` — show "Admin" nav item only for `admin` role

---

## Dependencies to Add

**`requirements.txt`:**
```
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
```

**`frontend/package.json`:**
```
jose          # for decoding JWT claims client-side (no new dep if using jwt-decode)
jwt-decode    # lightweight, ~1KB
```

---

## New Environment Variables

```bash
# .env
JWT_SECRET_KEY=<random 32-byte hex>     # required
JWT_TTL_HOURS=8                          # optional, default 8
```

---

## Implementation Order

| Step | What | Files | Est. effort |
|---|---|---|---|
| 1 | User store (SQLite schema + CRUD) | `api/users.py` | 0.5 days |
| 2 | Auth endpoints (login, register, /me) | `api/auth.py` | 1 day |
| 3 | Permission definitions + model check | `api/permissions.py` | 0.5 days |
| 4 | Wire auth into `/api/ask` endpoints | `api/main.py` | 0.5 days |
| 5 | Frontend login page + auth context | `LoginPage`, `AuthContext` | 1 day |
| 6 | Frontend protected routes + JWT header | `ProtectedRoute`, `api.ts` | 0.5 days |
| 7 | Role-aware UI (model picker, admin nav) | `ModelPicker`, `Sidebar` | 0.5 days |
| 8 | Admin user management page | `AdminPage.tsx` | 1 day |

**Total: ~5 days**

---

## What Doesn't Need to Change

- **Retrieval layer** — `HybridRetriever` already accepts a `tickers` filter. No changes needed.
- **AnswerEngine** — passes through `RetrieverConfig`; ticker restriction is transparent.
- **Chunking / embedding pipeline** — no per-user data; access control is query-time only.
- **CORS** — restrict `allow_origins` to the actual frontend domain when deploying.

---

## What to Defer

- **OAuth / SSO** — useful if integrating with a company's identity provider, but adds significant complexity. Add after basic JWT auth is stable.
- **Audit logging** — log (user, question, timestamp) to SQLite for compliance. Simple to add on top of the auth layer.
- **Token refresh** — 8-hour TTL is sufficient for now; add refresh tokens if users complain about being logged out.
- **Document-level ACL** — restricting access to individual filings (vs. company-level) adds complexity without clear use case yet.
