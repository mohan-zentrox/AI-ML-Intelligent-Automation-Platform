"""
Auth endpoints: password login (JWT) + scoped API key issuance.

Reference: FRD section "Access Control & RBAC".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import Principal, require_role
from app.core.security import Role, create_access_token, generate_api_key, verify_password
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyOut,
    LoginRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter_by(email=payload.email).first()
    if not user or not user.is_active or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(subject=user.id, role=user.role)
    return TokenResponse(access_token=token, role=user.role, role_id=user.role_id)


@router.post("/api-keys", response_model=ApiKeyCreateResponse)
def create_api_key(
    payload: ApiKeyCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(Role.ADMIN)),
) -> ApiKeyCreateResponse:
    """Admin-only: issue a new scoped API key for a given role.

    The full key is returned exactly once; only its salted hash is stored.
    """
    if payload.role not in {r.value for r in Role}:
        raise HTTPException(status_code=400, detail=f"Unknown role '{payload.role}'")

    full_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=principal.user_id,
        name=payload.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        role=payload.role,
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        role=api_key.role,
        key_prefix=api_key.key_prefix,
        api_key=full_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(Role.ADMIN)),
) -> list[ApiKeyOut]:
    keys = db.query(ApiKey).filter_by(user_id=principal.user_id).all()
    return [ApiKeyOut.model_validate(k) for k in keys]
