from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from openvegas.cli import cli
from openvegas.telemetry import get_dashboard_slices, reset_metrics
from openvegas.agent.local_tools import ToolExecutionResult
from openvegas.tui.diff_reviewer import parse_unified_patch


LONG_WORKFLOW_PROMPT = """You are my ML platform engineer. Execute this as one continuous workflow with tools, not advice:
1) Create `.openvegas_ml_runbook.md` in repo root with sections:
Summary, Data Contracts, Pipeline DAG, Training Plan, Eval Plan, Risks, Rollback.
2) Scan the repo and identify all inference/tooling orchestration code paths and schema migrations that affect runtime behavior.
3) Build a dependency map from request -> tool propose/start/result -> persistence -> replay/lease/telemetry.
4) Run targeted shell checks to validate current assumptions (rg/pytest subset) and capture outputs.
5) Patch `.openvegas_ml_runbook.md` with concrete findings and exact file references.
6) Add a “Failure Injection Plan” with 5 experiments:
stale_projection, active_mutation_in_progress, duplicate result hash conflict, heartbeat timeout, oversized payload.
7) Add a “Go/No-Go” section with explicit pass criteria and commands to verify.
8) Show final file contents.
"""


SCAFFOLD_CONTENT = """# .openvegas_ml_runbook.md

## Summary

## Data Contracts

## Pipeline DAG

## Training Plan

## Eval Plan

## Risks

## Rollback
"""


FINAL_CONTENT = """# .openvegas_ml_runbook.md

## Summary
End-to-end runtime/tooling flow reviewed and validated.

## Data Contracts
- Tool callbacks are CAS-only on `agent_run_tool_calls`.
- Runtime errors normalize to typed contract codes.

## Pipeline DAG
request -> propose -> start -> heartbeat -> result/cancel -> persistence -> replay/lease -> telemetry

## Training Plan
Run targeted orchestration tests + route contract tests on every change.

## Eval Plan
Verify completion criteria and mutation conflict handling under retry bounds.

## Risks
- Patch recovery drift can cause same-intent loops.
- Large payloads can exceed callback/result limits.

## Rollback
Revert CLI orchestration hardening commits and restore previous retry policy.

## Failure Injection Plan
1. stale_projection
2. active_mutation_in_progress
3. duplicate result hash conflict
4. heartbeat timeout
5. oversized payload

## Go/No-Go
Go only if:
- `pytest -q tests/test_agent`
- `pytest -q tests/e2e/test_chat_tool_flow.py`
"""


MASS_WORKFLOW_PROMPT = """You are my ML platform engineer. Execute one continuous workflow:
1) Create 10 Python modules in repo root named `dummy_module_00.py`..`dummy_module_09.py` with baseline transform functions.
2) Update all 10 modules with richer typed implementations and validation checks.
3) Search the repo for `def transform_`.
4) Run shell checks to confirm file count.
5) Read one module and summarize completion.
Stop only when all files are updated.
"""


def _module_v1(i: int) -> str:
    return (
        f"def transform_{i}(x):\n"
        f"    return x + {i}\n"
    )


def _module_v2(i: int) -> str:
    return (
        f"def transform_{i}(x):\n"
        f"    return x + {i}\n"
        f"UPDATED_{i} = True\n"
    )


def _create_single_dummy_module_patch(i: int) -> str:
    path = f"dummy_module_{i:02d}.py"
    return "".join(
        [
            "--- /dev/null\n",
            f"+++ {path}\n",
            "@@ -0,0 +1,2 @@\n",
            f"+def transform_{i}(x):\n",
            f"+    return x + {i}\n",
        ]
    )


def _update_single_dummy_module_patch(i: int) -> str:
    path = f"dummy_module_{i:02d}.py"
    return "".join(
        [
            f"--- {path}\n",
            f"+++ {path}\n",
            "@@ -1,2 +1,3 @@\n",
            f" def transform_{i}(x):\n",
            f"     return x + {i}\n",
            f"+UPDATED_{i} = True\n",
        ]
    )


class _FakeChatClient:
    instances: list["_FakeChatClient"] = []

    def __init__(self) -> None:
        self.thread_id = "thread-1"
        self.run_id = "run-1"
        self.run_version = 0
        self.signature = "sha256:" + ("a" * 64)
        self._tool_req_idx = 0
        self._ask_step = 0
        self._requests: dict[str, dict] = {}
        self.result_calls: list[dict] = []
        _FakeChatClient.instances.append(self)

    async def get_mode(self):
        return {"conversation_mode": "persistent"}

    async def agent_run_create(self, **_kwargs):
        return {
            "run_id": self.run_id,
            "run_version": self.run_version,
            "valid_actions_signature": self.signature,
        }

    async def agent_register_workspace(self, **_kwargs):
        return {"ok": True}

    async def ide_get_context(self, **_kwargs):
        raise RuntimeError("no bridge connected")

    async def ask(self, prompt, _provider, _model, **kwargs):
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {
                "thread_id": self.thread_id,
                "text": "Workflow complete. Runbook updated with findings.",
                "v_cost": "0.0",
            }

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Write",
                        "arguments": {"filepath": ".openvegas_ml_runbook.md", "content": SCAFFOLD_CONTENT},
                    }
                ],
            }
        if self._ask_step == 2:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Search",
                        "arguments": {"pattern": "agent_tool_propose", "path": "openvegas"},
                    }
                ],
            }
        if self._ask_step == 3:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Bash",
                        "arguments": {"command": "printf 'orchestration-smoke\\n'"},
                    }
                ],
            }
        if self._ask_step == 4:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Write",
                        "arguments": {"filepath": ".openvegas_ml_runbook.md", "content": FINAL_CONTENT},
                    }
                ],
            }
        return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0", "tool_calls": []}

    async def agent_tool_propose(self, **kwargs):
        self.run_version += 1
        self._tool_req_idx += 1
        tool_call_id = f"tc-{self._tool_req_idx}"
        execution_token = f"tok-{self._tool_req_idx}"
        req = {
            "tool_call_id": tool_call_id,
            "execution_token": execution_token,
            "tool_name": kwargs["tool_name"],
            "arguments": kwargs["arguments"],
            "shell_mode": kwargs.get("shell_mode") or "read_only",
            "timeout_sec": kwargs.get("timeout_sec") or 30,
        }
        self._requests[tool_call_id] = req
        return {
            "run_version": self.run_version,
            "valid_actions_signature": self.signature,
            "tool_request": req,
        }

    async def agent_tool_start(self, **_kwargs):
        self.run_version += 1
        return {"run_version": self.run_version, "valid_actions_signature": self.signature}

    async def agent_tool_result(self, **_kwargs):
        self.result_calls.append(dict(_kwargs))
        self.run_version += 1
        return {"run_version": self.run_version, "valid_actions_signature": self.signature}

    async def agent_tool_heartbeat(self, **_kwargs):
        return {"active": True, "status": "started"}

    async def agent_tool_cancel(self, **_kwargs):
        return {"ok": True}

    async def agent_run_get(self, **_kwargs):
        return {
            "run_version": self.run_version,
            "valid_actions_signature": self.signature,
            "current_state": "running",
            "valid_actions": [{"action": "handoff"}],
        }


class _FakeChatClientRealPatchFlow(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {
                "thread_id": self.thread_id,
                "text": "Workflow complete. Runbook updated with findings.",
                "v_cost": "0.0",
            }

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Write",
                        "arguments": {"filepath": ".openvegas_ml_runbook.md", "content": SCAFFOLD_CONTENT},
                    }
                ],
            }
        if self._ask_step == 2:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Search",
                        "arguments": {"pattern": "Runbook", "path": "."},
                    }
                ],
            }
        if self._ask_step == 3:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Bash",
                        "arguments": {"command": "printf 'orchestration-smoke\\n'"},
                    }
                ],
            }
        if self._ask_step == 4:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Write",
                        "arguments": {"filepath": ".openvegas_ml_runbook.md", "content": FINAL_CONTENT},
                    }
                ],
            }
        return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0", "tool_calls": []}


class _FakeChatClientMassDummyFlow(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {
                "thread_id": self.thread_id,
                "text": "Mass dummy workflow complete.",
                "v_cost": "0.0",
            }

        self._ask_step += 1
        step = self._ask_step
        if 1 <= step <= 10:
            idx = step - 1
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "fs_apply_patch",
                        "arguments": {"patch": _create_single_dummy_module_patch(idx)},
                    }
                ],
            }
        if 11 <= step <= 20:
            idx = step - 11
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "fs_apply_patch",
                        "arguments": {"patch": _update_single_dummy_module_patch(idx)},
                    }
                ],
            }
        if step == 21:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Search",
                        "arguments": {"pattern": "def transform_", "path": "."},
                    }
                ],
            }
        if step == 22:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Bash",
                        "arguments": {"command": "ls -1 dummy_module_*.py | wc -l"},
                    }
                ],
            }
        if step == 23:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {"tool_name": "Read", "arguments": {"filepath": "dummy_module_05.py"}}
                ],
            }
        return {
            "thread_id": self.thread_id,
            "text": "Done. All dummy modules were updated.",
            "v_cost": "0.0",
            "tool_calls": [],
        }


def test_chat_long_ml_workflow_prompt_end_to_end(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClient)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})

    patch_apply_calls = {"count": 0}

    def _fake_execute_tool_request(*, workspace_root: str, tool_name: str, arguments: dict, **_kwargs):
        if tool_name == "fs_apply_patch":
            patch_apply_calls["count"] += 1
            target = Path(workspace_root) / ".openvegas_ml_runbook.md"
            target.write_text(
                (SCAFFOLD_CONTENT if patch_apply_calls["count"] == 1 else FINAL_CONTENT).rstrip() + "\n",
                encoding="utf-8",
            )
            return ToolExecutionResult("succeeded", {"ok": True}, "", "")
        if tool_name == "fs_search":
            return ToolExecutionResult(
                "succeeded",
                {"ok": True, "matches": [{"path": "openvegas/agent/orchestration_service.py", "line": 1}]},
                "",
                "",
            )
        return ToolExecutionResult("succeeded", {"ok": True}, "", "")

    async def _fake_execute_shell_run_streaming(**_kwargs):
        return ToolExecutionResult(
            "succeeded",
            {"ok": True, "final_status_message": "Command completed", "exit_code": 0},
            "orchestration-smoke\n",
            "",
        )

    monkeypatch.setattr("openvegas.cli.execute_tool_request", _fake_execute_tool_request)
    monkeypatch.setattr("openvegas.cli.execute_shell_run_streaming", _fake_execute_shell_run_streaming)
    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        del path
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": ".openvegas_ml_runbook.md",
            "hunks_total": parsed.hunks_total,
            "decisions": [
                {"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)
            ],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)

    scripted_inputs = iter(["/approve allow", LONG_WORKFLOW_PROMPT, "/exit"])
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0
    assert "tool_execution_failed" not in result.output, result.output
    assert _FakeChatClient.instances
    assert _FakeChatClient.instances[-1]._ask_step >= 4
    assert patch_apply_calls["count"] >= 2
    assert terminal_diff_invocations["count"] >= 1

    runbook = tmp_path / ".openvegas_ml_runbook.md"
    assert runbook.exists()
    text = runbook.read_text(encoding="utf-8")
    assert ("## Summary" in text and "runtime/tooling flow reviewed" in text), (
        f"chat_output:\n{result.output}\n\nrunbook:\n{text}"
    )
    assert "## Data Contracts" in text and "CAS-only" in text
    assert "## Pipeline DAG" in text and "propose -> start -> heartbeat -> result/cancel" in text
    assert "## Failure Injection Plan" in text and "duplicate result hash conflict" in text
    assert "## Go/No-Go" in text and "pytest -q tests/test_agent" in text

    slices = get_dashboard_slices()
    assert "tool_apply_patch_retry_total_by_status" in slices
    assert "tool_loop_finalize_reason_distribution" in slices


def test_chat_long_ml_workflow_prompt_end_to_end_real_patch(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientRealPatchFlow)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        del path
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": ".openvegas_ml_runbook.md",
            "hunks_total": parsed.hunks_total,
            "decisions": [
                {"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)
            ],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)

    scripted_inputs = iter(["/approve allow", LONG_WORKFLOW_PROMPT, "/exit"])
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "tool_execution_failed" not in result.output, result.output
    assert _FakeChatClient.instances, result.output
    assert _FakeChatClient.instances[-1]._ask_step >= 4, result.output
    assert _FakeChatClient.instances[-1].result_calls, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output

    runbook = tmp_path / ".openvegas_ml_runbook.md"
    assert runbook.exists()
    text = runbook.read_text(encoding="utf-8")
    assert ("## Summary" in text and "runtime/tooling flow reviewed" in text), (
        f"chat_output:\n{result.output}\n\n"
        f"result_calls:\n{_FakeChatClient.instances[-1].result_calls}\n\n"
        f"runbook:\n{text}"
    )
    assert "## Data Contracts" in text and "CAS-only" in text
    assert "## Failure Injection Plan" in text and "duplicate result hash conflict" in text
    slices = get_dashboard_slices()
    assert slices["tool_apply_patch_same_intent_fail_total"] == 0


def test_chat_mass_dummy_code_changes_end_to_end_real_patch(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientMassDummyFlow)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_CHAT_MAX_TOOL_STEPS", "40")
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_DECISION", "accept_all")

    scripted_inputs = iter(["/approve allow", MASS_WORKFLOW_PROMPT, "/exit"])
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "tool_execution_failed" not in result.output, result.output
    assert _FakeChatClient.instances, result.output
    client = _FakeChatClient.instances[-1]
    assert client._ask_step >= 23, result.output
    assert len(client.result_calls) >= 23, result.output
    failed_calls = [
        {
            "tool_name": c.get("tool_name"),
            "result_status": c.get("result_status"),
            "reason_code": (c.get("result_payload") or {}).get("reason_code"),
            "patch_failure_code": (c.get("result_payload") or {}).get("patch_failure_code"),
            "detail": (c.get("result_payload") or {}).get("detail"),
            "patch_diagnostics": (c.get("result_payload") or {}).get("patch_diagnostics"),
            "stdout": (c.get("stdout") or "")[:400],
            "stderr": (c.get("stderr") or "")[:400],
        }
        for c in client.result_calls
        if str(c.get("result_status")) != "succeeded"
    ]
    assert not failed_calls, f"{result.output}\n\nfailed_calls={failed_calls!r}"

    files = sorted(tmp_path.glob("dummy_module_*.py"))
    assert len(files) == 10
    for idx, path in enumerate(files):
        text = path.read_text(encoding="utf-8")
        assert text == _module_v2(idx), f"{path} not updated to v2"

    patch_results = [
        c
        for c in client.result_calls
        if isinstance(c.get("result_payload"), dict)
        and "files_targeted" in c.get("result_payload", {})
    ]
    assert len(patch_results) >= 20, "expected ten create patches plus ten update patches"

    slices = get_dashboard_slices()
    assert slices["tool_apply_patch_same_intent_fail_total"] == 0
