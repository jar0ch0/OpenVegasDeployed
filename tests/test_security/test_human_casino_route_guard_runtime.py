from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.middleware.auth import get_current_user
from server.routes import casino_human


def _app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(casino_human.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-test"}
    return app


def test_human_casino_disabled_returns_503_before_service_call(monkeypatch):
    monkeypatch.setenv("CASINO_HUMAN_ENABLED", "0")
    called = {"service": False}

    def _boom_service():
        called["service"] = True
        raise AssertionError("service must not be resolved when feature is disabled")

    monkeypatch.setattr(casino_human, "get_human_casino_service", _boom_service)

    client = TestClient(_app_with_router())
    response = client.post(
        "/casino/human/sessions/start",
        json={"max_loss_v": 100, "max_rounds": 100, "idempotency_key": "idem-1"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == casino_human.HUMAN_CASINO_UNAVAILABLE_DETAIL
    assert called["service"] is False


def test_human_casino_enabled_passes_through_to_service(monkeypatch):
    monkeypatch.setenv("CASINO_HUMAN_ENABLED", "1")

    class _Service:
        def __init__(self):
            self.calls = 0

        async def start_session(self, **_kwargs):
            self.calls += 1
            return SimpleNamespace(status_code=200, body_text='{"ok":true}')

    svc = _Service()
    monkeypatch.setattr(casino_human, "get_human_casino_service", lambda: svc)

    client = TestClient(_app_with_router())
    response = client.post(
        "/casino/human/sessions/start",
        json={"max_loss_v": 100, "max_rounds": 100, "idempotency_key": "idem-2"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert svc.calls == 1


def test_human_casino_undefined_table_maps_to_503(monkeypatch):
    monkeypatch.setenv("CASINO_HUMAN_ENABLED", "1")
    monkeypatch.setattr(casino_human, "UndefinedTableError", RuntimeError)

    class _Service:
        async def start_session(self, **_kwargs):
            raise RuntimeError("relation missing")

    monkeypatch.setattr(casino_human, "get_human_casino_service", lambda: _Service())

    client = TestClient(_app_with_router())
    response = client.post(
        "/casino/human/sessions/start",
        json={"max_loss_v": 100, "max_rounds": 100, "idempotency_key": "idem-3"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == casino_human.HUMAN_CASINO_UNAVAILABLE_DETAIL
