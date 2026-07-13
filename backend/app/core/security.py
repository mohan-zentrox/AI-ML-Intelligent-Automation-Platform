"""
Auth primitives: password hashing, JWT session tokens, and scoped API keys.

Reference: FRD section "Access Control & RBAC" - roles are fixed to the
following set (never invent role names, never use real person names):

    T6-LEAD   - ML Lead / AI Engineer            -> role=admin
    T6-BE1    - Backend Engineer, Python          -> role=workflow_builder
    T6-DEV1   - Software Developer                -> role=reviewer
    T6-DATA1  - Data Analyst / ML Support          -> role=analyst
    T6-DATA2  - Data Analyst / ML Support          -> role=analyst
    T6-DATA3  - Data Analyst / ML Support          -> role=api_consumer

The mapping above is illustrative seed data only (see db/session.py seed
routine); role membership is actually driven by the `role` column on the
`users` / `api_keys` tables, not by identity.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

API_KEY_PREFIX = "syn"


class Role(str, Enum):
    ADMIN = "admin"
    WORKFLOW_BUILDER = "workflow_builder"
    REVIEWER = "reviewer"
    ANALYST = "analyst"
    API_CONSUMER = "api_consumer"


# Roles permitted to access a given capability. Kept centralized so that
# gating logic in deps.py stays a single source of truth.
ROLE_HIERARCHY_DESCRIPTION = {
    Role.ADMIN: "Full platform administration, user & key management.",
    Role.WORKFLOW_BUILDER: "Create/edit ingestion & workflow configuration.",
    Role.REVIEWER: "Human-in-the-loop review queue triage & decisions.",
    Role.ANALYST: "Read analytics/usage dashboards, run queries.",
    Role.API_CONSUMER: "Programmatic query/ingestion access only.",
}


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode = {"sub": subject, "role": role, "exp": expire, "type": "access"}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new scoped API key.

    Returns (full_key, key_prefix, key_hash). Only `key_hash` is persisted;
    `full_key` is shown to the caller exactly once at issuance time, mirroring
    how GitHub/Stripe-style API keys are handled.
    """
    raw = secrets.token_urlsafe(32)
    full_key = f"{API_KEY_PREFIX}_{raw}"
    key_prefix = full_key[:12]
    key_hash = hash_api_key(full_key)
    return full_key, key_prefix, key_hash


def hash_api_key(full_key: str) -> str:
    # HMAC-SHA256 with the app secret so stolen DB rows alone can't be used
    # to forge valid-looking hashes offline.
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), full_key.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_api_key(full_key: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(full_key), key_hash)
