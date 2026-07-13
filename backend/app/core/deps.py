"""
FastAPI dependencies: DB session, current-user resolution, and RBAC gating.

Supports two auth mechanisms, either of which resolves to an authenticated
"principal" (user_id + role):
  1. Bearer JWT (from POST /api/v1/auth/login) - interactive/browser use.
  2. `X-API-Key` header (from POST /api/v1/auth/api-keys) - programmatic /
     API Consumer use.

`require_role(*roles)` is the single reusable role-gate used across every
protected router - see FRD section "Access Control & RBAC".
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import Role, decode_access_token, verify_api_key
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.user import User


@dataclass
class Principal:
    user_id: str
    role: str
    role_id: str


def get_current_principal(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    if x_api_key:
        return _principal_from_api_key(db, x_api_key)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        return _principal_from_jwt(db, token)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing credentials: provide a Bearer token or X-API-Key header.",
    )


def _principal_from_jwt(db: Session, token: str) -> Principal:
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = db.query(User).filter_by(id=payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return Principal(user_id=user.id, role=user.role, role_id=user.role_id)


def _principal_from_api_key(db: Session, raw_key: str) -> Principal:
    prefix = raw_key[:12]
    candidates = db.query(ApiKey).filter_by(key_prefix=prefix, is_active=True).all()
    for candidate in candidates:
        if verify_api_key(raw_key, candidate.key_hash):
            user = db.query(User).filter_by(id=candidate.user_id).first()
            role_id = user.role_id if user else "unknown"
            return Principal(user_id=candidate.user_id, role=candidate.role, role_id=role_id)
    raise HTTPException(status_code=401, detail="Invalid API key")


def require_role(*allowed_roles: Role):
    """Dependency factory: 403s unless the caller's role is in `allowed_roles`."""

    allowed_values = {r.value for r in allowed_roles}

    def _checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{principal.role}' is not permitted to access this "
                    f"resource. Allowed roles: {sorted(allowed_values)}"
                ),
            )
        return principal

    return _checker
