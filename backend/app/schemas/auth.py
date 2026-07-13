from __future__ import annotations

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    role_id: str


class ApiKeyCreateRequest(BaseModel):
    name: str
    role: str


class ApiKeyCreateResponse(BaseModel):
    id: str
    name: str
    role: str
    key_prefix: str
    api_key: str  # full key, shown exactly once


class ApiKeyOut(BaseModel):
    id: str
    name: str
    role: str
    key_prefix: str
    is_active: bool

    model_config = {"from_attributes": True}
