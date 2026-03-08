from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import server.middleware.auth as auth_mod
from server.middleware.auth import get_current_user


def _request_with_token(token: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_get_current_user_fails_closed_when_secret_missing(monkeypatch):
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setattr(
        auth_mod.jwt,
        "get_unverified_header",
        lambda _token: {"alg": "HS256"},
    )

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_request_with_token("abc.def.ghi"))

    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_get_current_user_uses_configured_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setattr(
        auth_mod.jwt,
        "get_unverified_header",
        lambda _token: {"alg": "HS256"},
    )

    monkeypatch.setattr(
        auth_mod.jwt,
        "decode",
        lambda *_a, **_kw: {"sub": "user-123", "role": "authenticated"},
    )
    user = await get_current_user(_request_with_token("abc.def.ghi"))
    assert user["user_id"] == "user-123"
    assert user["account_type"] == "human"


@pytest.mark.asyncio
async def test_get_current_user_falls_back_to_supabase_validation_for_es256(monkeypatch):
    monkeypatch.setattr(
        auth_mod.jwt,
        "get_unverified_header",
        lambda _token: {"alg": "ES256"},
    )

    async def _fake_validate(token: str) -> dict:
        assert token == "abc.def.ghi"
        return {"user_id": "u-remote", "role": "authenticated", "account_type": "human"}

    monkeypatch.setattr(auth_mod, "_validate_with_supabase", _fake_validate)

    user = await get_current_user(_request_with_token("abc.def.ghi"))
    assert user["user_id"] == "u-remote"
