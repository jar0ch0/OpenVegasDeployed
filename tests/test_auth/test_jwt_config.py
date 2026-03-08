from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

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

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_request_with_token("abc.def.ghi"))

    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_get_current_user_uses_configured_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_request_with_token("abc.def.ghi"))

    assert exc.value.status_code == 401
