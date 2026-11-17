"""
Passwords (Argon2id), access tokens (JWT, HS256) and configuration checks.

Tokens are verified with an EXPLICIT algorithm list, so a token that claims
alg=none or a different algorithm is rejected, and exp/iat/sub are required.
"""
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import List

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings, settings

EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")
MAX_EMAIL_LENGTH = 254
MAX_PASSWORD_LENGTH = 256
ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}
MIN_JWT_SECRET_LENGTH = 32
MIN_METRICS_TOKEN_LENGTH = 24
_PLACEHOLDER_MARKERS = ("change", "placeholder", "example", "your-", "your_", "secret-key", "xxxx", "dummy")
_COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "password1234",
    "1234567890", "12345678910", "qwertyuiop", "letmein123", "iloveyou12",
    "administrator", "changeme123", "welcome123",
}


class TokenError(Exception):
    """The token is missing, malformed, expired, tampered with or signed with another key."""


# ------------------------------------------------------------------ passwords
@lru_cache(maxsize=8)
def _hasher(time_cost: int, memory_kib: int) -> PasswordHasher:
    return PasswordHasher(time_cost=time_cost, memory_cost=memory_kib, parallelism=1)


def password_hasher() -> PasswordHasher:
    return _hasher(settings.PASSWORD_HASH_TIME_COST, settings.PASSWORD_HASH_MEMORY_KIB)


def hash_password(password: str) -> str:
    return password_hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher().verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return password_hasher().check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


_dummy_hash_cache: dict = {}


def verify_dummy(password: str) -> None:
    """Spend the same time as a real check, so an unknown email can't be told apart by timing."""
    key = (settings.PASSWORD_HASH_TIME_COST, settings.PASSWORD_HASH_MEMORY_KIB)
    if key not in _dummy_hash_cache:
        _dummy_hash_cache[key] = hash_password("dummy-password-for-timing")
    verify_password(_dummy_hash_cache[key], password)


# ----------------------------------------------------------------- validation
def normalize_email(email: str) -> str:
    """Lowercase + trim; raises ValueError when it doesn't look like an address."""
    value = (email or "").strip().lower()
    if not value or len(value) > MAX_EMAIL_LENGTH or not EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    return value


def validate_password(password: str, email: str = "") -> None:
    """Raises ValueError with a human-readable reason when the password is too weak."""
    if password is None or len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")
    if not password.strip():
        raise ValueError("Password must not be blank")
    if len(set(password)) < 4:
        raise ValueError("Password is too repetitive")
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS:
        raise ValueError("Password is too common")
    if email and lowered in {email.lower(), email.lower().split("@")[0]}:
        raise ValueError("Password must not be your email address")


# --------------------------------------------------------------------- tokens
def create_access_token(user_id: int, email: str, now: datetime = None) -> str:
    if not settings.JWT_SECRET:
        raise TokenError("JWT_SECRET is not configured")
    now = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Returns the verified claims; raises TokenError for anything not issued by us and still valid."""
    if not settings.JWT_SECRET:
        raise TokenError("JWT_SECRET is not configured")
    if settings.JWT_ALGORITHM not in ALLOWED_JWT_ALGORITHMS:
        raise TokenError("Unsupported JWT algorithm configured")
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.isdigit():
        raise TokenError("Invalid subject")
    return claims


# -------------------------------------------------------------- configuration
def _looks_like_placeholder(secret: str) -> bool:
    lowered = secret.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS) or len(set(secret)) < 8


def security_problems(cfg: Settings) -> List[str]:
    """Everything that would make a deployment unsafe. Empty list = fine."""
    problems: List[str] = []
    if not cfg.AUTH_REQUIRED:
        problems.append("AUTH_REQUIRED is false: every endpoint is open to anyone who can reach the server")
    secret = cfg.JWT_SECRET or ""
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        problems.append(f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters")
    elif _looks_like_placeholder(secret):
        problems.append("JWT_SECRET looks like a placeholder; generate a random one")
    if cfg.JWT_ALGORITHM not in ALLOWED_JWT_ALGORITHMS:
        problems.append(f"JWT_ALGORITHM must be one of {sorted(ALLOWED_JWT_ALGORITHMS)}")
    if cfg.METRICS_TOKEN and len(cfg.METRICS_TOKEN) < MIN_METRICS_TOKEN_LENGTH:
        problems.append(f"METRICS_TOKEN must be at least {MIN_METRICS_TOKEN_LENGTH} characters when set")
    if any(origin == "*" for origin in cfg.cors_origins_list):
        problems.append("CORS_ORIGINS must list explicit origins, not '*'")
    return problems
