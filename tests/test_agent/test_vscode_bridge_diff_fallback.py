from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from openvegas.ide.vscode_bridge import VSCodeBridge
from openvegas.telemetry import get_metrics_snapshot, reset_metrics


@pytest.mark.asyncio
async def test_vscode_interactive_diff_accepts_valid_payload(monkeypatch):
    reset_metrics()
    payload = {
        "file_path": "a.py",
        "hunks_total": 1,
        "decisions": [{"hunk_index": 0, "decision": "accepted"}],
        "all_accepted": True,
        "timed_out": False,
    }
    monkeypatch.setenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_PAYLOAD", json.dumps(payload))
    bridge = VSCodeBridge(workspace_root=".")
    out = await bridge.show_diff_interactive("a.py", "print('x')\n")
    assert out["hunks_total"] == 1
    assert out["decisions"][0]["decision"] == "accepted"


@pytest.mark.asyncio
async def test_vscode_interactive_diff_rejects_malformed_payload(monkeypatch):
    reset_metrics()
    payload = {
        "file_path": "a.py",
        "hunks_total": 2,
        "decisions": [{"hunk_index": 0, "decision": "accepted"}],
        "all_accepted": False,
        "timed_out": False,
    }
    monkeypatch.setenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_PAYLOAD", json.dumps(payload))
    bridge = VSCodeBridge(workspace_root=".")
    with pytest.raises(ValueError):
        await bridge.show_diff_interactive("a.py", "print('x')\n")
    snap = get_metrics_snapshot()
    key = "tool_diff_fallback_total|from=ide_interactive,reason=malformed_payload,to=terminal"
    assert snap.get(key, 0) >= 1


@pytest.mark.asyncio
async def test_vscode_interactive_diff_timeout_reason_is_distinct(monkeypatch):
    reset_metrics()
    monkeypatch.setenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_TIMEOUT", "1")
    bridge = VSCodeBridge(workspace_root=".")
    with pytest.raises(asyncio.TimeoutError):
        await bridge.show_diff_interactive("a.py", "print('x')\n")
    snap = get_metrics_snapshot()
    key = "tool_diff_fallback_total|from=ide_interactive,reason=timeout,to=terminal"
    assert snap.get(key, 0) >= 1


@pytest.mark.asyncio
async def test_vscode_interactive_diff_bridge_error_fallback(monkeypatch):
    reset_metrics()
    monkeypatch.delenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_PAYLOAD", raising=False)
    monkeypatch.delenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_TIMEOUT", raising=False)
    monkeypatch.setenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_USE_COMMAND", "0")
    bridge = VSCodeBridge(workspace_root=".")
    out = await bridge.show_diff_interactive("a.py", "print('x')\n")
    assert "hunks_total" in out
    snap = get_metrics_snapshot()
    key = "tool_diff_fallback_total|from=ide_interactive,reason=bridge_error,to=terminal"
    assert snap.get(key, 0) >= 1


@pytest.mark.asyncio
async def test_vscode_interactive_diff_command_round_trip(monkeypatch, tmp_path: Path):
    reset_metrics()
    monkeypatch.delenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_PAYLOAD", raising=False)
    monkeypatch.delenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_TIMEOUT", raising=False)
    monkeypatch.setenv("OPENVEGAS_IDE_SHOW_DIFF_INTERACTIVE_USE_COMMAND", "1")
    monkeypatch.setenv("HOME", str(tmp_path))

    monkeypatch.setattr("openvegas.ide.vscode_bridge.shutil.which", lambda cmd: "/usr/bin/code" if cmd == "code" else None)

    class _Proc:
        async def wait(self) -> int:
            bridge_dir = tmp_path / ".openvegas" / "ide_bridge"
            req = json.loads((bridge_dir / "show_diff_request.json").read_text(encoding="utf-8"))
            response = {
                "file_path": req["path"],
                "hunks_total": 1,
                "decisions": [{"hunk_index": 0, "decision": "accepted"}],
                "all_accepted": True,
                "timed_out": False,
            }
            out = bridge_dir / f"show_diff_response_{req['request_id']}.json"
            out.write_text(json.dumps(response), encoding="utf-8")
            return 0

    async def _fake_spawn(*_args, **_kwargs):
        return _Proc()

    monkeypatch.setattr("openvegas.ide.vscode_bridge.asyncio.create_subprocess_exec", _fake_spawn)
    bridge = VSCodeBridge(workspace_root=".")
    out = await bridge.show_diff_interactive("a.py", "print('x')\n")
    assert out["hunks_total"] == 1
    assert out["decisions"][0]["decision"] == "accepted"
