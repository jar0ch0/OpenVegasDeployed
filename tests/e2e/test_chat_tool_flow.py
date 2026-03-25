from __future__ import annotations

from pathlib import Path

import pytest

from openvegas.agent.local_tools import execute_shell_run_streaming
from openvegas.agent.runtime_contracts import ToolPolicyDecision, evaluate_tool_policy
from openvegas.cli import _preprocess_tool_request_for_runtime


def test_prompt_search_triggers_fs_search():
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "fs_search", "arguments": {}},
        user_message='search for "result_submission_hash" across this repo',
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["tool_name"] == "fs_search"
    assert prepared["arguments"]["pattern"] == "result_submission_hash"


def test_patch_flow_requires_approval():
    decision = evaluate_tool_policy(
        tool_name="fs_apply_patch",
        shell_mode="mutating",
        approval_mode="ask",
    )
    assert decision == ToolPolicyDecision.ASK


@pytest.mark.asyncio
async def test_shell_streaming_with_heartbeat_and_cancel_shape(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    seen: list[str] = []
    result = await execute_shell_run_streaming(
        workspace_root=str(root),
        arguments={"command": "printf 'hello\\n'"},
        timeout_sec=5,
        on_stdout=lambda chunk: seen.append(chunk),
    )
    assert result.result_status == "succeeded"
    assert "hello" in result.stdout
    assert seen

