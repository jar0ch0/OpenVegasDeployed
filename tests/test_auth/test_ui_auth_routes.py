from __future__ import annotations

import importlib

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from openvegas.telemetry import get_metrics_snapshot, reset_metrics
from server.services import dependencies


def _load_ui_auth_module(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key in (
        "OPENVEGAS_RUNTIME_ENV",
        "ENV",
        "OPENVEGAS_COOKIE_SECURE",
        "OPENVEGAS_COOKIE_SAMESITE",
        "OPENVEGAS_REQUIRE_ORIGIN_ON_POST",
        "OPENVEGAS_TRUSTED_PROXY_HEADERS",
        "OPENVEGAS_TOOL_DEBUG",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    dependencies.current_flags.cache_clear()
    import server.routes.ui_auth as ui_auth

    return importlib.reload(ui_auth)


def _client_for(mod) -> TestClient:
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app)


@pytest.mark.parametrize(
    ("cookie_secure", "expected_cookie"),
    [
        ("0", "ov_refresh_token"),
        ("1", "__Host-ov_refresh_token"),
    ],
)
def test_login_sets_refresh_cookie_and_no_store_headers(
    monkeypatch: pytest.MonkeyPatch,
    cookie_secure: str,
    expected_cookie: str,
):
    mod = _load_ui_auth_module(
        monkeypatch,
        OPENVEGAS_RUNTIME_ENV="local",
        OPENVEGAS_COOKIE_SECURE=cookie_secure,
        OPENVEGAS_COOKIE_SAMESITE="lax",
        OPENVEGAS_REQUIRE_ORIGIN_ON_POST="1",
    )

    async def _fake_login(*, email: str, password: str):
        assert email == "test@example.com"
        assert password == "pw"
        return {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_at": 1700001234,
            "user": {"id": "u-1", "email": "test@example.com"},
        }

    monkeypatch.setattr(mod, "_supabase_token_password", _fake_login)
    client = _client_for(mod)

    resp = client.post(
        "/ui/auth/login",
        json={"email": "TEST@example.com", "password": "pw"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "access-1"
    assert isinstance(body["expires_at"], int)
    assert "refresh_token" not in body
    assert resp.headers.get("cache-control") == "no-store"
    set_cookie = resp.headers.get("set-cookie", "")
    assert expected_cookie in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/" in set_cookie


def test_missing_origin_rejected_in_production(monkeypatch: pytest.MonkeyPatch):
    reset_metrics()
    mod = _load_ui_auth_module(
        monkeypatch,
        OPENVEGAS_RUNTIME_ENV="production",
        OPENVEGAS_COOKIE_SECURE="1",
        OPENVEGAS_REQUIRE_ORIGIN_ON_POST="1",
    )

    async def _fake_login(*, email: str, password: str):
        return {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_at": 1700001234,
            "user": {"id": "u-1", "email": email},
        }

    monkeypatch.setattr(mod, "_supabase_token_password", _fake_login)
    client = _client_for(mod)
    resp = client.post("/ui/auth/login", json={"email": "x@y.com", "password": "pw"})
    assert resp.status_code == 403
    metrics = get_metrics_snapshot()
    key = "auth_csrf_block_total|proxy_trust_enabled=0,reason=missing_origin"
    assert metrics.get(key, 0) >= 1


def test_trusted_proxy_gate_controls_forwarded_header_usage(monkeypatch: pytest.MonkeyPatch):
    headers = {
        "Origin": "https://proxy.example",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "proxy.example",
    }

    mod_off = _load_ui_auth_module(
        monkeypatch,
        OPENVEGAS_RUNTIME_ENV="production",
        OPENVEGAS_COOKIE_SECURE="1",
        OPENVEGAS_REQUIRE_ORIGIN_ON_POST="1",
        OPENVEGAS_TRUSTED_PROXY_HEADERS="0",
    )
    c_off = _client_for(mod_off)
    blocked = c_off.post("/ui/auth/logout", headers=headers)
    assert blocked.status_code == 403

    mod_on = _load_ui_auth_module(
        monkeypatch,
        OPENVEGAS_RUNTIME_ENV="production",
        OPENVEGAS_COOKIE_SECURE="1",
        OPENVEGAS_REQUIRE_ORIGIN_ON_POST="1",
        OPENVEGAS_TRUSTED_PROXY_HEADERS="1",
    )
    c_on = _client_for(mod_on)
    allowed = c_on.post("/ui/auth/logout", headers=headers)
    assert allowed.status_code == 200


def test_refresh_rotation_invalidates_old_cookie(monkeypatch: pytest.MonkeyPatch):
    mod = _load_ui_auth_module(
        monkeypatch,
        OPENVEGAS_RUNTIME_ENV="local",
        OPENVEGAS_COOKIE_SECURE="0",
        OPENVEGAS_REQUIRE_ORIGIN_ON_POST="1",
    )
    valid_refresh_tokens = {"token-a"}

    async def _fake_refresh(refresh_token: str):
        if refresh_token not in valid_refresh_tokens:
            raise HTTPException(status_code=401, detail="Session expired")
        valid_refresh_tokens.remove(refresh_token)
        rotated = "token-b"
        valid_refresh_tokens.add(rotated)
        return {
            "access_token": "access-b",
            "refresh_token": rotated,
            "expires_at": 1700000000,
        }

    monkeypatch.setattr(mod, "_supabase_token_refresh", _fake_refresh)
    client = _client_for(mod)

    first = client.post(
        "/ui/auth/refresh",
        cookies={"ov_refresh_token": "token-a"},
        headers={"Origin": "http://testserver", "X-OpenVegas-Refresh-Trigger": "bootstrap"},
    )
    assert first.status_code == 200
    assert first.json()["access_token"] == "access-b"

    old_cookie = client.post(
        "/ui/auth/refresh",
        cookies={"ov_refresh_token": "token-a"},
        headers={"Origin": "http://testserver"},
    )
    assert old_cookie.status_code == 401

    new_cookie = client.post(
        "/ui/auth/refresh",
        cookies={"ov_refresh_token": "token-b"},
        headers={"Origin": "http://testserver"},
    )
    assert new_cookie.status_code == 200


def test_logout_response_shape_and_local_cookie_clear_on_revoke_error(monkeypatch: pytest.MonkeyPatch):
    mod = _load_ui_auth_module(
        monkeypatch,
        OPENVEGAS_RUNTIME_ENV="local",
        OPENVEGAS_COOKIE_SECURE="0",
        OPENVEGAS_REQUIRE_ORIGIN_ON_POST="1",
    )

    async def _fail_revoke(_token: str):
        raise RuntimeError("upstream-down")

    monkeypatch.setattr(mod, "revoke_refresh_session", _fail_revoke)
    client = _client_for(mod)
    resp = client.post(
        "/ui/auth/logout",
        cookies={"ov_refresh_token": "token-a"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["local_logout_succeeded"] is True
    assert body["upstream_revoke_succeeded"] is False
    assert "upstream-down" in str(body["upstream_revoke_error"])
    set_cookie = ",".join(resp.headers.get_list("set-cookie"))
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()
