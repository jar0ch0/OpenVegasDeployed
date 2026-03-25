from __future__ import annotations

from fastapi.testclient import TestClient

from openvegas.contracts.errors import APIErrorCode, ContractError
from server.main import app
from server.routes import agent_orchestration as agent_orch_routes
from server.middleware import auth as auth_middleware


class _SvcOK:
    async def create_run(self, **_kwargs):
        return {
            "run_id": "r1",
            "error": None,
            "detail": "",
            "retryable": False,
            "current_state": "running",
            "run_version": 0,
            "projection_version": 0,
            "valid_actions": [{"action": "cancel"}],
            "valid_actions_signature": "sha256:abc",
            "response_truncated": False,
            "response_hash": None,
        }

    async def get_run(self, **_kwargs):
        return {
            "run_id": "r1",
            "error": None,
            "detail": "",
            "retryable": False,
            "current_state": "running",
            "run_version": 2,
            "projection_version": 1,
            "valid_actions": [{"action": "cancel"}],
            "valid_actions_signature": "sha256:def",
            "response_truncated": False,
            "response_hash": None,
        }

    async def transition_run(self, **_kwargs):
        return type(
            "Result",
            (),
            {
                "status_code": 200,
                "payload": {
                    "run_id": "r1",
                    "error": None,
                    "detail": "",
                    "retryable": False,
                    "current_state": "running",
                    "run_version": 3,
                    "projection_version": 1,
                    "valid_actions": [{"action": "cancel"}],
                    "valid_actions_signature": "sha256:ghi",
                    "response_truncated": False,
                    "response_hash": None,
                },
            },
        )()

    async def consume_approval(self, **_kwargs):
        return type("Result", (), {"status_code": 200, "payload": {"error": None}})()

    async def check_handoff_block(self, **_kwargs):
        return {"error": APIErrorCode.HANDOFF_BLOCKED.value, "handoff_block_reason": "pending_approval"}

    async def register_workspace(self, **_kwargs):
        return {"error": None, "run_id": "r1", "runtime_session_id": "s1"}

    async def propose_tool_call(self, **_kwargs):
        return type(
            "Result",
            (),
            {
                "status_code": 200,
                "payload": {
                    "error": None,
                    "run_id": "r1",
                    "run_version": 3,
                    "valid_actions_signature": "sha256:ghi",
                    "tool_request": {
                        "tool_call_id": "tc1",
                        "execution_token": "tok1",
                        "tool_name": "fs_read",
                        "arguments": {"path": "README.md"},
                        "payload_hash": "a" * 64,
                        "requires_approval": False,
                        "shell_mode": "read_only",
                        "timeout_sec": 5,
                    },
                },
            },
        )()

    async def start_tool_call(self, **_kwargs):
        return type("Result", (), {"status_code": 200, "payload": {"error": None, "tool_call_id": "tc1"}})()

    async def heartbeat_tool_call(self, **_kwargs):
        return {"active": True}

    async def cancel_tool_call(self, **_kwargs):
        return type("Result", (), {"status_code": 200, "payload": {"error": None, "tool_status": "cancelled"}})()

    async def result_tool_call(self, **_kwargs):
        return type("Result", (), {"status_code": 200, "payload": {"error": None, "tool_call_id": "tc1"}})()


class _SvcStale:
    async def transition_run(self, **_kwargs):
        raise ContractError(APIErrorCode.STALE_PROJECTION, "stale")


class _SvcActiveToolBlock:
    async def check_handoff_block(self, **_kwargs):
        return {"error": APIErrorCode.HANDOFF_BLOCKED.value, "handoff_block_reason": "active_tool_execution"}


def _override_user():
    return {"user_id": "85add5d1-aaad-4caa-8422-8cd41ff400f7", "role": "authenticated"}


def test_orchestration_create_run_envelope_shape(monkeypatch):
    monkeypatch.setattr(agent_orch_routes, "get_agent_orchestration_service", lambda: _SvcOK())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    resp = client.post("/agent/runs", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "r1"
    assert "error" in body
    assert body["error"] is None
    assert body["current_state"] == "running"
    assert "valid_actions_signature" in body
    assert body["projection_version"] == 0
    app.dependency_overrides.clear()


def test_orchestration_handoff_block_shape(monkeypatch):
    monkeypatch.setattr(agent_orch_routes, "get_agent_orchestration_service", lambda: _SvcOK())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    resp = client.post("/agent/runs/r1/ui/handoff-check", json={})
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == APIErrorCode.HANDOFF_BLOCKED.value
    assert body["handoff_block_reason"] == "pending_approval"
    app.dependency_overrides.clear()


def test_orchestration_handoff_block_shape_active_tool(monkeypatch):
    monkeypatch.setattr(agent_orch_routes, "get_agent_orchestration_service", lambda: _SvcActiveToolBlock())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    resp = client.post("/agent/runs/r1/ui/handoff-check", json={})
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == APIErrorCode.HANDOFF_BLOCKED.value
    assert body["handoff_block_reason"] == "active_tool_execution"
    app.dependency_overrides.clear()


def test_orchestration_transition_stale_projection_maps_to_409(monkeypatch):
    monkeypatch.setattr(agent_orch_routes, "get_agent_orchestration_service", lambda: _SvcStale())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    resp = client.post(
        "/agent/runs/r1/transition",
        json={
            "action": "handoff",
            "payload": {},
            "idempotency_key": "k1",
            "expected_run_version": 0,
            "expected_valid_actions_signature": "sha256:abc",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == APIErrorCode.STALE_PROJECTION.value
    app.dependency_overrides.clear()


def test_orchestration_tool_runtime_endpoints_shape(monkeypatch):
    monkeypatch.setattr(agent_orch_routes, "get_agent_orchestration_service", lambda: _SvcOK())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    reg = client.post(
        "/agent/runs/r1/session/register-workspace",
        json={
            "runtime_session_id": "s1",
            "workspace_root": "/tmp/work",
            "workspace_fingerprint": "sha256:" + ("a" * 64),
            "git_root": "/tmp/work",
        },
    )
    assert reg.status_code == 200
    assert reg.json()["runtime_session_id"] == "s1"

    prop = client.post(
        "/agent/runs/r1/tools/propose",
        json={
            "runtime_session_id": "s1",
            "expected_run_version": 3,
            "expected_valid_actions_signature": "sha256:ghi",
            "idempotency_key": "k1",
            "tool_name": "fs_read",
            "arguments": {"path": "README.md"},
            "shell_mode": "read_only",
            "timeout_sec": 5,
            "plan_mode": False,
        },
    )
    assert prop.status_code == 200
    assert prop.json()["tool_request"]["tool_call_id"] == "tc1"

    start = client.post(
        "/agent/runs/r1/tools/start",
        json={
            "runtime_session_id": "s1",
            "tool_call_id": "tc1",
            "execution_token": "tok1",
            "expected_run_version": 3,
            "expected_valid_actions_signature": "sha256:ghi",
            "idempotency_key": "k2",
        },
    )
    assert start.status_code == 200

    hb = client.post(
        "/agent/runs/r1/tools/heartbeat",
        json={
            "runtime_session_id": "s1",
            "tool_call_id": "tc1",
            "execution_token": "tok1",
        },
    )
    assert hb.status_code == 200
    assert hb.json()["active"] is True

    res = client.post(
        "/agent/runs/r1/tools/result",
        json={
            "runtime_session_id": "s1",
            "tool_call_id": "tc1",
            "execution_token": "tok1",
            "result_status": "succeeded",
            "result_payload": {"ok": True},
            "stdout": "",
            "stderr": "",
        },
    )
    assert res.status_code == 200

    cancel = client.post(
        "/agent/runs/r1/tools/tc1/cancel",
        json={
            "runtime_session_id": "s1",
            "execution_token": "tok1",
        },
    )
    assert cancel.status_code == 200
    assert cancel.json()["tool_status"] == "cancelled"
    app.dependency_overrides.clear()


def test_tool_result_rejects_non_raw_hash_format(monkeypatch):
    monkeypatch.setattr(agent_orch_routes, "get_agent_orchestration_service", lambda: _SvcOK())
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user

    client = TestClient(app)
    res = client.post(
        "/agent/runs/r1/tools/result",
        json={
            "runtime_session_id": "s1",
            "tool_call_id": "tc1",
            "execution_token": "tok1",
            "result_status": "succeeded",
            "result_payload": {"ok": True},
            "stdout": "",
            "stderr": "",
            "stdout_sha256": "sha256:" + ("a" * 64),
            "stderr_sha256": "b" * 64,
            "result_submission_hash": "c" * 64,
        },
    )
    assert res.status_code == 422
    app.dependency_overrides.clear()


def test_stale_fence_applies_to_start_only_not_result():
    start_fields = set(agent_orch_routes.StartToolRequest.model_fields.keys())
    result_fields = set(agent_orch_routes.ToolResultRequest.model_fields.keys())
    assert "expected_run_version" in start_fields
    assert "expected_valid_actions_signature" in start_fields
    assert "expected_run_version" not in result_fields
    assert "expected_valid_actions_signature" not in result_fields
