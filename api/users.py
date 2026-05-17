"""
User store — SQLite-backed CRUD for user accounts.

Schema
------
users (id, email, hashed_password, role, allowed_tickers, is_active, created_at)

allowed_tickers is stored as a JSON string: '["AAPL","MSFT"]' or the sentinel
string "*" meaning unrestricted access to all companies.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "users.db"


@dataclass
class User:
    id:              int
    email:           str
    hashed_password: str
    role:            str            # "admin" | "analyst" | "viewer"
    allowed_tickers: str            # "*" or JSON array string
    is_active:       bool
    created_at:      str

    def tickers_list(self) -> list[str] | None:
        """Return list of allowed tickers, or None if unrestricted."""
        if self.allowed_tickers == "*":
            return None
        try:
            return json.loads(self.allowed_tickers)
        except (json.JSONDecodeError, TypeError):
            return None


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the users table and seed a default admin if the table is empty."""
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                email           TEXT    UNIQUE NOT NULL,
                hashed_password TEXT    NOT NULL,
                role            TEXT    NOT NULL DEFAULT 'viewer',
                allowed_tickers TEXT    NOT NULL DEFAULT '*',
                is_active       BOOLEAN NOT NULL DEFAULT 1,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # Seed three demo users on first boot (one per role).
    import bcrypt as _bcrypt

    _SEED_USERS = [
        ("admin@example.com",   "admin-pass-123",   "admin",   "*"),
        ("analyst@example.com", "analyst-pass-123", "analyst", "*"),
        ("viewer@example.com",  "viewer-pass-123",  "viewer",  '["AAPL","MSFT","NVDA","GOOG","AMZN"]'),
    ]
    for email, password, role, tickers in _SEED_USERS:
        if not get_user_by_email(email):
            hashed = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
            create_user(email=email, hashed_password=hashed, role=role, allowed_tickers=tickers)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        hashed_password=row["hashed_password"],
        role=row["role"],
        allowed_tickers=row["allowed_tickers"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )


def get_user_by_email(email: str) -> User | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_id(user_id: int) -> User | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return _row_to_user(row) if row else None


def create_user(
    email: str,
    hashed_password: str,
    role: str = "viewer",
    allowed_tickers: str = "*",
) -> User:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO users (email, hashed_password, role, allowed_tickers)
               VALUES (?, ?, ?, ?)""",
            (email, hashed_password, role, allowed_tickers),
        )
    user = get_user_by_email(email)
    assert user is not None
    return user


def list_users() -> list[User]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_user(r) for r in rows]


def update_user(
    user_id: int,
    role: str | None = None,
    allowed_tickers: str | None = None,
    is_active: bool | None = None,
) -> None:
    updates: dict[str, object] = {}
    if role            is not None: updates["role"]            = role
    if allowed_tickers is not None: updates["allowed_tickers"] = allowed_tickers
    if is_active       is not None: updates["is_active"]       = int(is_active)
    if not updates:
        return
    fields = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as conn:
        conn.execute(
            f"UPDATE users SET {fields} WHERE id = ?",
            (*updates.values(), user_id),
        )


def delete_user(user_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
