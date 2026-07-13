"""Auth primitive tests - app/core/security.py."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.deps import Principal, require_role
from app.core.security import (
    Role,
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    verify_api_key,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"
    assert verify_password("correct-horse-battery-staple", hashed)
    assert not verify_password("wrong-password", hashed)


def test_jwt_roundtrip_contains_subject_and_role():
    token = create_access_token(subject="user-123", role=Role.ADMIN.value)
    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert payload["role"] == Role.ADMIN.value


def test_jwt_rejects_tampered_token():
    token = create_access_token(subject="user-123", role=Role.ADMIN.value)
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
    with pytest.raises(ValueError):
        decode_access_token(tampered)


def test_api_key_generation_and_verification():
    full_key, prefix, key_hash = generate_api_key()
    assert full_key.startswith("syn_")
    assert full_key.startswith(prefix)
    assert verify_api_key(full_key, key_hash)
    assert not verify_api_key("syn_some-other-key", key_hash)


def test_api_key_is_unique_per_call():
    key1, _, _ = generate_api_key()
    key2, _, _ = generate_api_key()
    assert key1 != key2


def test_require_role_allows_matching_role():
    checker = require_role(Role.ADMIN, Role.REVIEWER)
    principal = Principal(user_id="u1", role=Role.REVIEWER.value, role_id="T6-DEV1")
    # Calling the inner dependency function directly (bypassing FastAPI's
    # Depends() resolution) is valid since it's a plain callable.
    assert checker(principal) is principal


def test_require_role_rejects_non_matching_role():
    checker = require_role(Role.ADMIN)
    principal = Principal(user_id="u1", role=Role.API_CONSUMER.value, role_id="T6-DATA3")
    with pytest.raises(HTTPException) as exc_info:
        checker(principal)
    assert exc_info.value.status_code == 403
