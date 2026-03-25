from __future__ import annotations

from fastapi.testclient import TestClient

from server.main import app
from server.middleware import auth as auth_middleware
from server.routes import ide_bridge as ide_bridge_routes
from openvegas.ide.bridge_registry import get_bridge_registry


class _FakeDB:
    def __init__(self, ok: bool = True):
        self.ok = ok

    async def fetchrow(self, *_args, **_kwargs):
        return {"ok": True} if self.ok else None


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
        return []

    async def read_buffer(self, *_args, **_kwargs):
        return "buffer"

    async def get_context(self):
        return {
            "open_files": [],
            "active_file": None,
            "cursor": None,
            "selection": None,
            "diagnostics": [],
            "terminal_history": [],
        }


def _override_user():
    return {"user_id": "85add5d1-aaad-4caa-8422-8cd41ff400f7", "role": "authenticated"}


def test_ide_bridge_register_and_dispatch(monkeypatch):
    get_bridge_registry()._sessions.clear()
    monkeypatch.setattr(ide_bridge_routes, "get_db", lambda: _FakeDB(ok=True))
    monkeypatch.setattr(ide_bridge_routes, "create_bridge", lambda *_args, **_kwargs: _FakeBridge())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    reg = client.post(
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
    assert reg.status_code == 200
    assert reg.json()["ok"] is True

    open_file = client.post(
        "/ide/open-file",
        json={
            "run_id": "r1",
            "runtime_session_id": "s1",
            "path": "/tmp/a.py",
            "line": 1,
            "col": 1,
        },
    )
    assert open_file.status_code == 200
    assert open_file.json()["ok"] is True

    run_cmd = client.post(
        "/ide/run-command",
        json={
            "run_id": "r1",
            "runtime_session_id": "s1",
            "command": "echo hi",
        },
    )
    assert run_cmd.status_code == 200
    assert run_cmd.json()["ok"] is True

    ctx = client.post("/ide/context", json={"run_id": "r1", "runtime_session_id": "s1"})
    assert ctx.status_code == 200
    assert "open_files" in ctx.json()
    app.dependency_overrides.clear()


def test_ide_bridge_register_rejects_actor_mismatch(monkeypatch):
    get_bridge_registry()._sessions.clear()
    monkeypatch.setattr(ide_bridge_routes, "get_db", lambda: _FakeDB(ok=True))
    monkeypatch.setattr(ide_bridge_routes, "create_bridge", lambda *_args, **_kwargs: _FakeBridge())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    reg = client.post(
        "/ide/register",
        json={
            "run_id": "r1",
            "runtime_session_id": "s1",
            "actor_id": "00000000-0000-0000-0000-000000000000",
            "ide_type": "vscode",
            "workspace_root": "/tmp",
            "workspace_fingerprint": "sha256:" + ("a" * 64),
        },
    )
    assert reg.status_code == 409
    assert reg.json()["error"] == "invalid_transition"
    app.dependency_overrides.clear()


def test_ide_bridge_dispatch_rejects_binding_mismatch(monkeypatch):
    get_bridge_registry()._sessions.clear()
    monkeypatch.setattr(ide_bridge_routes, "get_db", lambda: _FakeDB(ok=False))
    monkeypatch.setattr(ide_bridge_routes, "create_bridge", lambda *_args, **_kwargs: _FakeBridge())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    open_file = client.post(
        "/ide/open-file",
        json={
            "run_id": "r1",
            "runtime_session_id": "s1",
            "path": "/tmp/a.py",
            "line": 1,
            "col": 1,
        },
    )
    assert open_file.status_code == 409
    assert open_file.json()["error"] == "invalid_transition"
    app.dependency_overrides.clear()

