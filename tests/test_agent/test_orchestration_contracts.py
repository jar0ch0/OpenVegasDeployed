from __future__ import annotations

from decimal import Decimal
import pytest

from openvegas.agent.orchestration_contracts import (
    MutatingResponseEnvelope,
    canonical_json,
    canonicalize_valid_actions,
    valid_actions_signature,
)
from openvegas.agent.orchestration_service import AgentOrchestrationService


def test_canonical_json_normalizes_nested_decimals_and_key_order():
    raw = {
        "b": [{"z": Decimal("1.250000"), "a": 2}],
        "a": {"y": Decimal("3.000000"), "x": True},
    }
    text = canonical_json(raw)
    assert text == '{"a":{"x":true,"y":"3.000000"},"b":[{"a":2,"z":"1.250000"}]}'


def test_valid_actions_ordering_is_deterministic_for_approval_runlevel_and_other():
    actions = [
        {"action": "other_beta", "resource_id": "r2"},
        {"action": "cancel"},
        {"action": "approve", "tool_call_id": "bbb"},
        {"action": "handoff"},
        {"action": "other_alpha", "resource_id": "r1"},
        {"action": "approve", "tool_call_id": "aaa"},
        {"action": "resume"},
    ]
    ordered = canonicalize_valid_actions(actions)
    assert [a["action"] for a in ordered] == [
        "approve",
        "approve",
        "resume",
        "cancel",
        "handoff",
        "other_alpha",
        "other_beta",
    ]
    assert [a.get("tool_call_id") for a in ordered[:2]] == ["aaa", "bbb"]


def test_valid_actions_signature_is_prefixed_sha256_lower_hex():
    sig = valid_actions_signature(
        7,
        [{"action": "cancel"}, {"action": "approve", "tool_call_id": "1"}],
    )
    assert sig.startswith("sha256:")
    hex_part = sig.split(":", 1)[1]
    assert len(hex_part) == 64
    assert hex_part == hex_part.lower()


def test_mutating_envelope_success_keeps_error_null_field_present():
    env = MutatingResponseEnvelope(
        error=None,
        detail="",
        retryable=False,
        current_state="running",
        run_version=3,
        projection_version=0,
        valid_actions=[{"action": "cancel"}],
        valid_actions_signature="sha256:abc",
    ).as_dict()
    assert "error" in env
    assert env["error"] is None


def test_tool_argument_normalization_maps_common_aliases():
    svc = AgentOrchestrationService(db=None)

    fs_read = svc._normalize_tool_arguments(
        tool_name="fs_read",
        arguments={"file_path": "/tmp/a.txt"},
    )
    assert fs_read["path"] == "/tmp/a.txt"

    fs_search = svc._normalize_tool_arguments(
        tool_name="fs_search",
        arguments={"query": "hello", "directory": "src"},
    )
    assert fs_search["pattern"] == "hello"
    assert fs_search["path"] == "src"

    shell = svc._normalize_tool_arguments(
        tool_name="shell_run",
        arguments={"cmd": "echo hi"},
    )
    assert shell["command"] == "echo hi"


def test_tool_argument_normalization_lifts_nested_path():
    svc = AgentOrchestrationService(db=None)
    fs_read = svc._normalize_tool_arguments(
        tool_name="fs_read",
        arguments={"file": {"path": "/tmp/nested.txt"}},
    )
    assert fs_read["path"] == "/tmp/nested.txt"


def test_tool_argument_normalization_recovers_fs_search_pattern_from_nested_alias():
    svc = AgentOrchestrationService(db=None)
    fs_search = svc._normalize_tool_arguments(
        tool_name="fs_search",
        arguments={
            "pattern": {"kind": "regex"},
            "meta": {"keyword": "result_submission_hash"},
            "directory": "openvegas",
        },
    )
    assert fs_search["pattern"] == "result_submission_hash"
    assert fs_search["path"] == "openvegas"


def test_tool_argument_normalization_recovers_fs_apply_patch_from_nested_alias():
    svc = AgentOrchestrationService(db=None)
    patch = svc._normalize_tool_arguments(
        tool_name="fs_apply_patch",
        arguments={"payload": {"changes": "--- a.txt\n+++ a.txt\n@@ -1 +1 @@\n-a\n+b\n"}},
    )
    assert patch["patch"].startswith("--- a.txt")


def test_tool_argument_normalization_recovers_shell_command_from_nested_alias():
    svc = AgentOrchestrationService(db=None)
    shell = svc._normalize_tool_arguments(
        tool_name="shell_run",
        arguments={"payload": {"script": "ls -la | head -20"}},
    )
    assert shell["command"] == "ls -la | head -20"


class _FakeTx:
    async def fetchrow(self, query: str, *args):
        text = " ".join(query.split()).lower()
        if "from agent_run_tool_calls" in text and "id <> $2::uuid" in text:
            # When ignoring the currently finishing tool call, no other started tool remains.
            return None
        if "from agent_run_tool_calls" in text and "status = 'started'" in text:
            return {"exists": 1}
        if "from run_status_projection" in text:
            return {"projection_version": 0}
        return None

    async def fetch(self, query: str, *args):
        text = " ".join(query.split()).lower()
        if "from agent_tool_approvals" in text:
            return []
        return []


@pytest.mark.asyncio
async def test_success_envelope_ignores_current_started_tool_on_terminalization():
    svc = AgentOrchestrationService(db=None)
    tx = _FakeTx()
    run = {"id": "00000000-0000-0000-0000-000000000001", "state": "running", "version": 0}

    env = await svc._success_envelope_tx(
        tx=tx,
        run=run,
        actor_id="u1",
        actor_role_class="user",
        ignore_started_tool_call_id="00000000-0000-0000-0000-0000000000aa",
    )
    actions = env["valid_actions"]
    names = {a["action"] for a in actions}
    assert "cancel" in names
    assert "handoff" in names
