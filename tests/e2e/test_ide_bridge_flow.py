from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

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


@pytest.mark.parametrize("ide_type", ["vscode", "jetbrains"])
def test_open_file_and_run_command_dispatch(ide_type: str):
    reg = get_bridge_registry()
    reg._sessions.clear()
    reg._event_queues.clear()
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user
    ide_bridge_routes.get_db = lambda: _FakeDB()
    ide_bridge_routes.create_bridge = lambda *_args, **_kwargs: _FakeBridge()
    client = TestClient(app)

    register = client.post(
        "/ide/register",
        json={
            "run_id": "r1",
            "runtime_session_id": "s1",
            "actor_id": "85add5d1-aaad-4caa-8422-8cd41ff400f7",
            "ide_type": ide_type,
            "workspace_root": "/tmp",
            "workspace_fingerprint": "sha256:" + ("a" * 64),
        },
    )
    assert register.status_code == 200

    open_file = client.post(
        "/ide/message",
        json={
            "id": "m1",
            "type": "request",
            "method": "open_file",
            "params": {"run_id": "r1", "runtime_session_id": "s1", "path": "/tmp/a.py", "line": 1, "col": 1},
        },
    )
    assert open_file.status_code == 200
    assert open_file.json()["error"] is None

    run_cmd = client.post(
        "/ide/message",
        json={
            "id": "m2",
            "type": "request",
            "method": "run_command",
            "params": {"run_id": "r1", "runtime_session_id": "s1", "command": "echo hi"},
        },
    )
    assert run_cmd.status_code == 200
    assert run_cmd.json()["error"] is None
    app.dependency_overrides.clear()


def test_reconnect_resume_registration():
    reg = get_bridge_registry()
    reg._sessions.clear()
    reg._event_queues.clear()
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user
    ide_bridge_routes.get_db = lambda: _FakeDB()
    ide_bridge_routes.create_bridge = lambda *_args, **_kwargs: _FakeBridge()
    client = TestClient(app)

    first = client.post(
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
    second = client.post(
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
    assert first.status_code == 200
    assert first.json()["resumed"] is False
    assert second.status_code == 200
    assert second.json()["resumed"] is True
    app.dependency_overrides.clear()
