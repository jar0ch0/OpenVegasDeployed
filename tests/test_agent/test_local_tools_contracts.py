from __future__ import annotations

import asyncio
import pytest
from pathlib import Path

import openvegas.agent.local_tools as local_tools
from openvegas.agent.local_tools import (
    execute_shell_run_streaming,
    execute_tool_request,
    workspace_fingerprint,
)


def test_workspace_fingerprint_is_identity_oriented(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    fp1 = workspace_fingerprint(str(root))
    fp2 = workspace_fingerprint(str(root))
    assert fp1 == fp2
    assert fp1.startswith("sha256:")


def test_fs_read_blocks_path_escape(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    res = execute_tool_request(
        workspace_root=str(root),
        tool_name="fs_read",
        arguments={"path": str(outside)},
        shell_mode="read_only",
        timeout_sec=5,
    )
    assert res.result_status == "blocked"
    assert res.result_payload.get("reason_code") == "workspace_path_out_of_bounds"


def test_fs_read_blocks_binary_file(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    binary = root / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02")
    res = execute_tool_request(
        workspace_root=str(root),
        tool_name="fs_read",
        arguments={"path": "blob.bin"},
        shell_mode="read_only",
        timeout_sec=5,
    )
    assert res.result_status == "blocked"
    assert res.result_payload.get("reason_code") == "binary_file_unsupported"


def test_fs_search_skips_binary_files(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("hello world\n", encoding="utf-8")
    (root / "b.bin").write_bytes(b"\x00\x01hello")
    res = execute_tool_request(
        workspace_root=str(root),
        tool_name="fs_search",
        arguments={"pattern": "hello", "path": ".", "recursive": True},
        shell_mode="read_only",
        timeout_sec=5,
    )
    assert res.result_status == "succeeded"
    matches = res.result_payload.get("matches", [])
    assert any(m.get("path") == "a.txt" for m in matches)
    assert not any(m.get("path") == "b.bin" for m in matches)


def test_shell_run_streaming_path_via_sync_tool_exec(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    res = execute_tool_request(
        workspace_root=str(root),
        tool_name="shell_run",
        arguments={"command": "printf 'ok\\n'"},
        shell_mode="read_only",
        timeout_sec=5,
    )
    assert res.result_status == "succeeded"
    assert "ok" in res.stdout
    assert "final_status_message" in res.result_payload


def test_fs_read_bounds_result_payload_content_size(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "big.md"
    target.write_text(("a" * 50000) + "\n", encoding="utf-8")
    res = execute_tool_request(
        workspace_root=str(root),
        tool_name="fs_read",
        arguments={"path": "big.md"},
        shell_mode="read_only",
        timeout_sec=5,
    )
    assert res.result_status == "succeeded"
    content = str(res.result_payload.get("content", ""))
    assert len(content) <= local_tools.MAX_FS_READ_RESULT_CONTENT_CHARS
    assert bool(res.result_payload.get("content_truncated")) is True
    assert len(res.stdout) > len(content)


def test_fs_apply_patch_failure_returns_diagnostics(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    # Force a context mismatch so patch dry-run fails with deterministic diagnostics.
    bad_patch = "\n".join(
        [
            "--- a.txt",
            "+++ a.txt",
            "@@ -99,1 +99,1 @@",
            "-missing",
            "+replacement",
            "",
        ]
    )
    res = execute_tool_request(
        workspace_root=str(root),
        tool_name="fs_apply_patch",
        arguments={"patch": bad_patch},
        shell_mode="mutating",
        timeout_sec=5,
    )
    assert res.result_status == "failed"
    assert res.result_payload.get("reason_code") == "tool_execution_failed"
    assert isinstance(res.result_payload.get("patch_failure_code"), str)
    diagnostics = res.result_payload.get("patch_diagnostics")
    assert isinstance(diagnostics, dict)
    assert isinstance(diagnostics.get("attempts"), list)
    assert diagnostics.get("target_files") == ["a.txt"]


@pytest.mark.asyncio
async def test_shell_run_background_mode_returns_job_id(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    local_tools._BACKGROUND_JOBS.clear()
    res = await execute_shell_run_streaming(
        workspace_root=str(root),
        arguments={"command": "sleep 0.1; echo bg", "background": True},
        timeout_sec=5,
    )
    assert res.result_status == "succeeded"
    assert res.result_payload.get("status") == "running_in_background"
    job_id = res.result_payload.get("job_id")
    assert isinstance(job_id, str)
    assert res.result_payload.get("final_status_message", "").startswith("Command is running in the background")
    # Drain the background job so asyncio subprocess transports close in-test.
    for _ in range(30):
        await asyncio.sleep(0.05)
        resumed = await execute_shell_run_streaming(
            workspace_root=str(root),
            arguments={"foreground_job_id": str(job_id)},
            timeout_sec=5,
        )
        if resumed.result_payload.get("status") == "foreground_result":
            break


@pytest.mark.asyncio
async def test_shell_run_foreground_transition_returns_final_status(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    local_tools._BACKGROUND_JOBS.clear()
    start = await execute_shell_run_streaming(
        workspace_root=str(root),
        arguments={"command": "sleep 0.1; printf 'done\\n'", "background": True},
        timeout_sec=5,
    )
    assert start.result_status == "succeeded"
    job_id = str(start.result_payload.get("job_id"))
    resumed = None
    for _ in range(30):
        await asyncio.sleep(0.05)
        candidate = await execute_shell_run_streaming(
            workspace_root=str(root),
            arguments={"foreground_job_id": job_id},
            timeout_sec=5,
        )
        if candidate.result_payload.get("status") == "foreground_result":
            resumed = candidate
            break
    assert resumed is not None
    assert resumed.result_status == "succeeded"
    assert resumed.result_payload.get("status") == "foreground_result"
    assert resumed.result_payload.get("final_status_message") == "Background command completed"
    assert "done" in resumed.stdout
