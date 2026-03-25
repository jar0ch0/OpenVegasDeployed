from __future__ import annotations

from fastapi.testclient import TestClient

from openvegas.ide.bridge_registry import get_bridge_registry
from server.main import app
from server.middleware import auth as auth_middleware
from server.routes import ide_bridge as ide_bridge_routes


class _FakeDB:
    async def fetchrow(self, *_args, **_kwargs):
        return {"ok": True}


class _FakeBridge:
    async def open_file(self, *_args, **_kwargs):
        return None

    async def run_command(self, *_args, **_kwargs):
        return None

    async def show_diff(self, path: str, *_args, **_kwargs):
        return {
            "file_path": path,
            "hunks_total": 1,
            "decisions": [{"hunk_index": 0, "decision": "accepted"}],
            "all_accepted": True,
            "timed_out": False,
        }

    async def get_open_files(self):
        return ["/tmp/a.py"]

    async def read_buffer(self, *_args, **_kwargs):
        return "buffer"

    async def get_context(self):
        return {
            "open_files": ["/tmp/a.py"],
            "active_file": "/tmp/a.py",
            "cursor": None,
            "selection": None,
            "diagnostics": [],
            "terminal_history": [],
        }


def _override_user():
    return {"user_id": "85add5d1-aaad-4caa-8422-8cd41ff400f7", "role": "authenticated"}


def _register(client: TestClient):
    return client.post(
        "/ide/register",
        json={
            "run_id": "r1",
            "runtime_session_id": "s1",
            "actor_id": "85add5d1-aaad-4caa-8422-8cd41ff400f7",
            "ide_type": "vscode",
            "workspace_root": "/tmp",
            "workspace_fingerprint": "sha256:" + ("a" * 64),
        },
    )


def test_ide_register_supports_resume(monkeypatch):
    reg = get_bridge_registry()
    reg._sessions.clear()
    reg._event_queues.clear()
    monkeypatch.setattr(ide_bridge_routes, "get_db", lambda: _FakeDB())
    monkeypatch.setattr(ide_bridge_routes, "create_bridge", lambda *_args, **_kwargs: _FakeBridge())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    first = _register(client)
    second = _register(client)
    assert first.status_code == 200
    assert first.json()["resumed"] is False
    assert second.status_code == 200
    assert second.json()["resumed"] is True
    app.dependency_overrides.clear()


def test_ide_message_envelope_dispatch_and_events(monkeypatch):
    reg = get_bridge_registry()
    reg._sessions.clear()
    reg._event_queues.clear()
    monkeypatch.setattr(ide_bridge_routes, "get_db", lambda: _FakeDB())
    monkeypatch.setattr(ide_bridge_routes, "create_bridge", lambda *_args, **_kwargs: _FakeBridge())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    _register(client)
    msg = client.post(
        "/ide/message",
        json={
            "id": "req1",
            "type": "request",
            "method": "get_context",
            "params": {"run_id": "r1", "runtime_session_id": "s1"},
        },
    )
    assert msg.status_code == 200
    body = msg.json()
    assert body["id"] == "req1"
    assert body["type"] == "response"
    assert body["error"] is None
    assert "open_files" in body["result"]

    key = ("r1", "s1")
    assert key in reg._event_queues
    assert reg._event_queues[key].qsize() >= 1
    app.dependency_overrides.clear()

