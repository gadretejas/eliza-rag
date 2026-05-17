"""
Authentication — JWT creation, validation, and FastAPI router.

Endpoints
---------
POST /auth/login    — returns a JWT given email + password
POST /auth/register — creates a new user (admin-only in production)
GET  /auth/me       — returns the current user's profile
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

from api.users import User, create_user, get_user_by_email, get_user_by_id

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "insecure-dev-secret-change-me")
ALGORITHM  = "HS256"
TTL_HOURS  = int(os.environ.get("JWT_TTL_HOURS", "8"))

_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Token claims ──────────────────────────────────────────────────────────────

@dataclass
class TokenClaims:
    user_id:         int
    email:           str
    role:            str
    allowed_tickers: str   # "*" or JSON array string


def _make_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TTL_HOURS)
    payload = {
        "sub":             str(user.id),
        "email":           user.email,
        "role":            user.role,
        "allowed_tickers": user.allowed_tickers,
        "exp":             expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenClaims(
        user_id=int(payload["sub"]),
        email=payload["email"],
        role=payload["role"],
        allowed_tickers=payload.get("allowed_tickers", "*"),
    )


async def get_current_user(token: str = Depends(_oauth2)) -> TokenClaims:
    """FastAPI dependency — validates JWT and returns decoded claims."""
    claims = decode_token(token)
    # Verify the user still exists and is active
    user = get_user_by_id(claims.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )
    return claims


def require_admin(claims: TokenClaims = Depends(get_current_user)) -> TokenClaims:
    """FastAPI dependency — additionally requires admin role."""
    if claims.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return claims


# ── Request / response schemas ────────────────────────────────────────────────

class LoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    role:         str
    email:        str

class RegisterRequest(BaseModel):
    email:           str
    password:        str
    role:            str = "viewer"
    allowed_tickers: str = "*"    # "*" or JSON array e.g. '["AAPL","MSFT"]'

class UserProfile(BaseModel):
    id:              int
    email:           str
    role:            str
    allowed_tickers: str
    is_active:       bool


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(form: OAuth2PasswordRequestForm = Depends()) -> LoginResponse:
    user = get_user_by_email(form.username)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not _verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return LoginResponse(
        access_token=_make_token(user),
        role=user.role,
        email=user.email,
    )


@router.post("/register", response_model=UserProfile, status_code=201)
def register(
    req: RegisterRequest,
    _: TokenClaims = Depends(require_admin),
) -> UserProfile:
    """Create a new user. Requires admin JWT."""
    if get_user_by_email(req.email):
        raise HTTPException(status_code=409, detail="Email already registered")

    # Validate allowed_tickers format
    if req.allowed_tickers != "*":
        try:
            tickers = json.loads(req.allowed_tickers)
            if not isinstance(tickers, list):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="allowed_tickers must be '*' or a JSON array of ticker strings",
            )

    hashed = _hash_password(req.password)
    user   = create_user(
        email=req.email,
        hashed_password=hashed,
        role=req.role,
        allowed_tickers=req.allowed_tickers,
    )
    return UserProfile(
        id=user.id,
        email=user.email,
        role=user.role,
        allowed_tickers=user.allowed_tickers,
        is_active=user.is_active,
    )


@router.get("/me", response_model=UserProfile)
def me(claims: TokenClaims = Depends(get_current_user)) -> UserProfile:
    user = get_user_by_id(claims.user_id)
    assert user
    return UserProfile(
        id=user.id,
        email=user.email,
        role=user.role,
        allowed_tickers=user.allowed_tickers,
        is_active=user.is_active,
    )
