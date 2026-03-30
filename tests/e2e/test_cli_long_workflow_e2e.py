from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from openvegas.cli import cli
from openvegas.telemetry import get_dashboard_slices, get_metrics_snapshot, reset_metrics
from openvegas.agent.local_tools import ToolExecutionResult
from openvegas.tui.diff_reviewer import parse_unified_patch
from openvegas.tui.approval_menu import ApprovalDecision


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


class _FakeChatClientReadThenCodeOnly(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        if self._ask_step == 2:
            return {
                "thread_id": self.thread_id,
                "text": (
                    "Here is the modified file:\n\n"
                    "```python\n"
                    "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                    "def add(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the sum of a and b.\"\"\"\n"
                    "    return a + b\n\n"
                    "def sub(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the difference of a and b.\"\"\"\n"
                    "    return a - b\n\n"
                    "def mul(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the product of a and b.\"\"\"\n"
                    "    return a * b\n\n"
                    "def divide(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the quotient of a and b with guard.\"\"\"\n"
                    "    if b == 0:\n"
                    "        raise ValueError(\"Cannot divide by zero.\")\n"
                    "    return a / b\n"
                    "```\n"
                ),
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        return {"thread_id": self.thread_id, "text": "Applied.", "v_cost": "0.0", "tool_calls": []}


class _FakeChatClientReadThenCodeNoTools(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        if self._ask_step == 2:
            return {
                "thread_id": self.thread_id,
                "text": (
                    "Here is the modified file:\n\n"
                    "```python\n"
                    "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                    "def add(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the sum of a and b.\"\"\"\n"
                    "    return a + b\n\n"
                    "def sub(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the difference of a and b.\"\"\"\n"
                    "    return a - b\n\n"
                    "def mul(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the product of a and b.\"\"\"\n"
                    "    return a * b\n\n"
                    "def divide(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the quotient of a and b with guard.\"\"\"\n"
                    "    if b == 0:\n"
                    "        raise ValueError(\"Cannot divide by zero.\")\n"
                    "    return a / b\n"
                    "```\n"
                ),
                "v_cost": "0.0",
                "tool_calls": [],
            }
        return {"thread_id": self.thread_id, "text": "Applied.", "v_cost": "0.0", "tool_calls": []}


class _FakeChatClientReadThenMultipleCodeBlocks(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        if self._ask_step == 2:
            return {
                "thread_id": self.thread_id,
                "text": (
                    "Apply this update:\n\n"
                    "```text\n"
                    "usage: run divide(4,2)\n"
                    "```\n"
                    "```python\n"
                    "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                    "def add(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the sum of a and b.\"\"\"\n"
                    "    return a + b\n\n"
                    "def sub(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the difference of a and b.\"\"\"\n"
                    "    return a - b\n\n"
                    "def mul(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the product of a and b.\"\"\"\n"
                    "    return a * b\n\n"
                    "def divide(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the quotient of a and b with guard.\"\"\"\n"
                    "    if b == 0:\n"
                    "        raise ValueError(\"Cannot divide by zero.\")\n"
                    "    return a / b\n"
                    "```\n"
                ),
                "v_cost": "0.0",
                "tool_calls": [],
            }
        return {"thread_id": self.thread_id, "text": "Applied.", "v_cost": "0.0", "tool_calls": []}


class _FakeChatClientReadThenCodeNoToolsGuardFinalize(_FakeChatClientReadThenCodeNoTools):
    async def ask(self, prompt, _provider, _model, **kwargs):
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            # If finalize is called before synth-write has executed a patch, signal failure.
            if not any(str(r.get("tool_name")) == "fs_apply_patch" for r in self._requests.values()):
                return {
                    "thread_id": self.thread_id,
                    "text": "PREMATURE_FINALIZE_BEFORE_SYNTH_WRITE",
                    "v_cost": "0.0",
                }
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}
        return await super().ask(prompt, _provider, _model, **kwargs)


class _FakeChatClientReadDuplicateThenCodeNoTools(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            # If finalize is called before synth-write patch path runs, fail test visibly.
            if not any(str(r.get("tool_name")) == "fs_apply_patch" for r in self._requests.values()):
                return {
                    "thread_id": self.thread_id,
                    "text": "PREMATURE_FINALIZE_AFTER_DUPLICATE_READ",
                    "v_cost": "0.0",
                }
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        if self._ask_step == 2:
            # Duplicate read-only turn; should not finalize as completed.
            return {
                "thread_id": self.thread_id,
                "text": "Checked current file contents.",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        if self._ask_step == 3:
            return {
                "thread_id": self.thread_id,
                "text": (
                    "Here is the modified file:\n\n"
                    "```python\n"
                    "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                    "def add(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the sum of a and b.\"\"\"\n"
                    "    return a + b\n\n"
                    "def sub(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the difference of a and b.\"\"\"\n"
                    "    return a - b\n\n"
                    "def mul(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the product of a and b.\"\"\"\n"
                    "    return a * b\n\n"
                    "def divide(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the quotient of a and b with guard.\"\"\"\n"
                    "    if b == 0:\n"
                    "        raise ValueError(\"Cannot divide by zero.\")\n"
                    "    return a / b\n"
                    "```\n"
                ),
                "v_cost": "0.0",
                "tool_calls": [],
            }
        return {"thread_id": self.thread_id, "text": "Applied.", "v_cost": "0.0", "tool_calls": []}


class _FakeChatClientCodeOnlyNoTools(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": (
                    "Here is the modified file:\n\n"
                    "```python\n"
                    "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                    "def add(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the sum of a and b.\"\"\"\n"
                    "    return a + b\n\n"
                    "def sub(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the difference of a and b.\"\"\"\n"
                    "    return a - b\n\n"
                    "def mul(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the product of a and b.\"\"\"\n"
                    "    return a * b\n\n"
                    "def divide(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the quotient of a and b with guard.\"\"\"\n"
                    "    if b == 0:\n"
                    "        raise ValueError(\"Cannot divide by zero.\")\n"
                    "    return a / b\n"
                    "```\n"
                ),
                "v_cost": "0.0",
                "tool_calls": [],
            }
        return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0", "tool_calls": []}


class _FakeChatClientUnfencedCodeNoTools(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": (
                    "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                    "def add(a: float, b: float) -> float:\n"
                    "    return a + b\n\n"
                    "def divide(a: float, b: float) -> float:\n"
                    "    if b == 0:\n"
                    "        raise ValueError(\"Cannot divide by zero.\")\n"
                    "    return a / b\n"
                ),
                "v_cost": "0.0",
                "tool_calls": [],
            }
        return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0", "tool_calls": []}


class _FakeChatClientFinalizeCodeBlockNoTools(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            if not any(str(r.get("tool_name")) == "fs_apply_patch" for r in self._requests.values()):
                return {
                    "thread_id": self.thread_id,
                    "text": (
                        "FINALIZE_CODE_BLOCK_SENTINEL\n\n"
                        "```python\n"
                        "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                        "def add(a: float, b: float) -> float:\n"
                        "    \"\"\"Return the sum of a and b.\"\"\"\n"
                        "    return a + b\n\n"
                        "def sub(a: float, b: float) -> float:\n"
                        "    \"\"\"Return the difference of a and b.\"\"\"\n"
                        "    return a - b\n\n"
                        "def mul(a: float, b: float) -> float:\n"
                        "    \"\"\"Return the product of a and b.\"\"\"\n"
                        "    return a * b\n\n"
                        "def divide(a: float, b: float) -> float:\n"
                        "    \"\"\"Return the quotient of a and b with guard.\"\"\"\n"
                        "    if b == 0:\n"
                        "        raise ValueError(\"Cannot divide by zero.\")\n"
                        "    return a / b\n"
                        "```\n"
                    ),
                    "v_cost": "0.0",
                }
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        return {
            "thread_id": self.thread_id,
            "text": "Checked current file state.",
            "v_cost": "0.0",
            "tool_calls": [],
        }


class _FakeChatClientFinalizeMultipleCodeBlocksNoTools(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            if not any(str(r.get("tool_name")) == "fs_apply_patch" for r in self._requests.values()):
                block = (
                    "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                    "def add(a: float, b: float) -> float:\n"
                    "    return a + b\n"
                )
                return {
                    "thread_id": self.thread_id,
                    "text": (
                        "Two options:\n\n"
                        f"```python\n{block}```\n\n"
                        f"```python\n{block}```\n"
                    ),
                    "v_cost": "0.0",
                }
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        return {
            "thread_id": self.thread_id,
            "text": "Checked current file state.",
            "v_cost": "0.0",
            "tool_calls": [],
        }


class _FakeChatClientFinalizeNoCodeBlockNoTools(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            if not any(str(r.get("tool_name")) == "fs_apply_patch" for r in self._requests.values()):
                return {
                    "thread_id": self.thread_id,
                    "text": "I would add divide() and a zero-division guard, but no fenced code block is provided here.",
                    "v_cost": "0.0",
                }
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": "",
                "v_cost": "0.0",
                "tool_calls": [
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    }
                ],
            }
        return {
            "thread_id": self.thread_id,
            "text": "Checked current file state.",
            "v_cost": "0.0",
            "tool_calls": [],
        }


class _FakeChatClientReadThenCodeNoToolsPromptLog(_FakeChatClientReadThenCodeNoTools):
    def __init__(self) -> None:
        super().__init__()
        self.prompt_log: list[str] = []

    async def ask(self, prompt, _provider, _model, **kwargs):
        self.prompt_log.append(str(prompt or ""))
        return await super().ask(prompt, _provider, _model, **kwargs)


class _FakeChatClientReadThenCodeNoToolsBridgeUnavailable(_FakeChatClientReadThenCodeNoToolsPromptLog):
    async def ide_get_context(self, **_kwargs):
        return {"active_file": "tests/fixtures/diff_accept_demo/calc.py"}


class _FakeChatClientReadThenCodeNoToolsMalformedDiff(_FakeChatClientReadThenCodeNoToolsPromptLog):
    async def ide_get_context(self, **_kwargs):
        return {"active_file": "tests/fixtures/diff_accept_demo/calc.py"}

    async def ide_message(self, **_kwargs):
        # malformed: hunks_total does not match decision count
        return {
            "result": {
                "file_path": "tests/fixtures/diff_accept_demo/calc.py",
                "hunks_total": 2,
                "decisions": [{"hunk_index": 0, "decision": "accepted"}],
                "all_accepted": False,
                "timed_out": False,
            }
        }


class _FakeChatClientInvalidWritePlusReadThenCode(_FakeChatClient):
    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        enable_tools = bool(kwargs.get("enable_tools", False))
        if not enable_tools:
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.0"}

        self._ask_step += 1
        if self._ask_step == 1:
            return {
                "thread_id": self.thread_id,
                "text": (
                    "Here's the updated version:\n\n"
                    "```python\n"
                    "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
                    "def add(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the sum of a and b.\"\"\"\n"
                    "    return a + b\n\n"
                    "def sub(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the difference of a and b.\"\"\"\n"
                    "    return a - b\n\n"
                    "def mul(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the product of a and b.\"\"\"\n"
                    "    return a * b\n\n"
                    "def divide(a: float, b: float) -> float:\n"
                    "    \"\"\"Return the quotient of a and b with guard.\"\"\"\n"
                    "    if b == 0:\n"
                    "        raise ValueError(\"Cannot divide by zero.\")\n"
                    "    return a / b\n"
                    "```\n"
                ),
                "v_cost": "0.0",
                "tool_calls": [
                    {"tool_name": "Write", "arguments": {"filepath": ""}},
                    {
                        "tool_name": "Read",
                        "arguments": {"filepath": "tests/fixtures/diff_accept_demo/calc.py"},
                    },
                ],
            }
        return {"thread_id": self.thread_id, "text": "Applied.", "v_cost": "0.0", "tool_calls": []}


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


def test_chat_synthesizes_write_when_model_only_returns_code_block(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeOnly)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "tool_execution_failed" not in result.output, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    assert _FakeChatClient.instances, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text
    assert "Cannot divide by zero." in text
    assert "\"\"\"Return the sum of a and b.\"\"\"" in text


def test_chat_synthesizes_write_after_read_only_then_zero_tool_calls(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "tool_execution_failed" not in result.output, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    assert _FakeChatClient.instances, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert any(str(r.get("tool_name")) == "fs_read" for r in reqs), result.output
    assert any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text
    assert "Cannot divide by zero." in text


def test_chat_synthesizes_write_with_observation_target_fallback(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Add divide(), zero-division guard, and docstrings to this file.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text
    assert "Cannot divide by zero." in text


def test_chat_synthesizes_write_with_multiple_code_blocks(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenMultipleCodeBlocks)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text
    assert "Cannot divide by zero." in text


def test_synth_write_fires_before_empty_list_finalization(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeNoToolsGuardFinalize)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "PREMATURE_FINALIZE_BEFORE_SYNTH_WRITE" not in result.output, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    assert _FakeChatClient.instances, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert any(str(r.get("tool_name")) == "fs_read" for r in reqs), result.output
    assert any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text


def test_duplicate_read_does_not_premature_finalize_before_mutation(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadDuplicateThenCodeNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "PREMATURE_FINALIZE_AFTER_DUPLICATE_READ" not in result.output, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text


def test_post_finalize_intercepts_code_block_and_mutates(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientFinalizeCodeBlockNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")
    monkeypatch.setenv("OPENVEGAS_WORKFLOW_STALL_LIMIT_ITERS", "2")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "FINALIZE_CODE_BLOCK_SENTINEL" not in result.output, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text
    snapshot = get_metrics_snapshot()
    assert snapshot.get("tool_synth_write_from_code_block_total|reason=post_finalize_interception", 0) >= 1


def test_post_finalize_interception_single_attempt_no_loop(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientFinalizeCodeBlockNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")
    monkeypatch.setenv("OPENVEGAS_WORKFLOW_STALL_LIMIT_ITERS", "2")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "edit blocked: post_finalize_intercept_already_attempted" not in result.output, result.output
    snapshot = get_metrics_snapshot()
    assert snapshot.get("tool_synth_write_from_code_block_total|reason=post_finalize_interception", 0) == 1


def test_post_finalize_two_fenced_blocks_blocks_without_mutation(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientFinalizeMultipleCodeBlocksNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_WORKFLOW_STALL_LIMIT_ITERS", "2")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
        "def add(a: float, b: float) -> float:\n"
        "    return a + b\n\n"
        "def sub(a: float, b: float) -> float:\n"
        "    return a - b\n\n"
        "def mul(a: float, b: float) -> float:\n"
        "    return a * b\n"
    )
    target.write_text(original, encoding="utf-8")

    scripted_inputs = iter(
        [
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "edit blocked: multiple_code_blocks_ambiguous" in result.output, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert not any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    assert target.read_text(encoding="utf-8") == original
    snapshot = get_metrics_snapshot()
    assert snapshot.get("tool_mutation_blocked_total|reason=multiple_code_blocks_ambiguous", 0) >= 1
    assert snapshot.get("tool_loop_finalize_reason|reason=mutation_required_but_unavailable", 0) >= 1


def test_post_finalize_interception_blocks_hard_when_no_code_block(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientFinalizeNoCodeBlockNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_WORKFLOW_STALL_LIMIT_ITERS", "2")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
        "def add(a: float, b: float) -> float:\n"
        "    return a + b\n\n"
        "def sub(a: float, b: float) -> float:\n"
        "    return a - b\n\n"
        "def mul(a: float, b: float) -> float:\n"
        "    return a * b\n"
    )
    target.write_text(original, encoding="utf-8")

    scripted_inputs = iter(
        [
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "edit blocked: zero_code_blocks" in result.output, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert not any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    assert target.read_text(encoding="utf-8") == original
    snapshot = get_metrics_snapshot()
    assert snapshot.get("tool_mutation_blocked_total|reason=zero_code_blocks", 0) >= 1
    assert snapshot.get("tool_loop_finalize_reason|reason=mutation_required_but_unavailable", 0) >= 1


def test_post_finalize_reports_non_tty_block_reason_instead_of_attempted(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientFinalizeCodeBlockNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")
    monkeypatch.setenv("OPENVEGAS_WORKFLOW_STALL_LIMIT_ITERS", "2")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
        "def add(a: float, b: float) -> float:\n"
        "    return a + b\n\n"
        "def sub(a: float, b: float) -> float:\n"
        "    return a - b\n\n"
        "def mul(a: float, b: float) -> float:\n"
        "    return a * b\n"
    )
    target.write_text(original, encoding="utf-8")

    # Force non-tty diff rejection even in test runner.
    monkeypatch.setattr(
        "openvegas.cli.review_patch_terminal",
        lambda **_kwargs: {
            "file_path": "tests/fixtures/diff_accept_demo/calc.py",
            "hunks_total": 1,
            "decisions": [{"hunk_index": 0, "decision": "rejected"}],
            "all_accepted": False,
            "timed_out": False,
            "error": "non_tty",
        },
    )

    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "edit blocked: non_interactive_terminal" in result.output, result.output
    assert "edit blocked: post_finalize_intercept_already_attempted" not in result.output, result.output
    assert target.read_text(encoding="utf-8") == original


def test_blocked_intercept_outcome_emits_finalize_reason_metric(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientFinalizeMultipleCodeBlocksNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_WORKFLOW_STALL_LIMIT_ITERS", "2")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
        "def add(a: float, b: float) -> float:\n"
        "    return a + b\n\n"
        "def sub(a: float, b: float) -> float:\n"
        "    return a - b\n\n"
        "def mul(a: float, b: float) -> float:\n"
        "    return a * b\n"
    )
    target.write_text(original, encoding="utf-8")

    scripted_inputs = iter(
        [
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert "edit blocked: multiple_code_blocks_ambiguous" in result.output, result.output
    assert target.read_text(encoding="utf-8") == original

    snapshot = get_metrics_snapshot()
    assert snapshot.get("tool_loop_finalize_reason|reason=mutation_required_but_unavailable", 0) >= 1


def test_chat_synthesized_write_still_requires_approval_in_ask_mode(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeOnly)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
        "def add(a: float, b: float) -> float:\n"
        "    return a + b\n\n"
        "def sub(a: float, b: float) -> float:\n"
        "    return a - b\n\n"
        "def mul(a: float, b: float) -> float:\n"
        "    return a * b\n"
    )
    target.write_text(original, encoding="utf-8")

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    approval_calls = {"count": 0}

    def _allow_once_approval(**_kwargs):
        approval_calls["count"] += 1
        return ApprovalDecision.ALLOW_ONCE

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    monkeypatch.setattr("openvegas.cli.choose_approval", _allow_once_approval)
    scripted_inputs = iter(
        [
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    assert approval_calls["count"] >= 1, result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text


def test_chat_recovers_when_model_emits_invalid_write_plus_read(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientInvalidWritePlusReadThenCode)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    assert _FakeChatClient.instances, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text
    assert "Cannot divide by zero." in text


def test_chat_synth_write_triggers_on_zero_tool_calls_with_code_block(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientCodeOnlyNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    terminal_diff_invocations = {"count": 0}

    def _accept_all_terminal_diff(*, path: str, patch_text: str, **_kwargs):
        terminal_diff_invocations["count"] += 1
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "accepted"} for idx in range(parsed.hunks_total)],
            "all_accepted": True,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _accept_all_terminal_diff)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert terminal_diff_invocations["count"] >= 1, result.output
    assert _FakeChatClient.instances, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    text = target.read_text(encoding="utf-8")
    assert "def divide(" in text
    assert "Cannot divide by zero." in text


def test_chat_non_edit_prompt_with_fenced_code_does_not_synthesize_mutation(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeOnly)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
        "def add(a: float, b: float) -> float:\n"
        "    return a + b\n\n"
        "def sub(a: float, b: float) -> float:\n"
        "    return a - b\n\n"
        "def mul(a: float, b: float) -> float:\n"
        "    return a * b\n"
    )
    target.write_text(original, encoding="utf-8")

    scripted_inputs = iter(
        [
            "Show an example implementation for tests/fixtures/diff_accept_demo/calc.py, but do not edit files.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    assert _FakeChatClient.instances, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert not any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    assert target.read_text(encoding="utf-8") == original


def test_chat_edit_prompt_with_unfenced_code_surfaces_block_reason(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientUnfencedCodeNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_CHAT_MAX_TOOL_STEPS", "4")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
        "def add(a: float, b: float) -> float:\n"
        "    return a + b\n\n"
        "def sub(a: float, b: float) -> float:\n"
        "    return a - b\n\n"
        "def mul(a: float, b: float) -> float:\n"
        "    return a * b\n"
    )
    target.write_text(original, encoding="utf-8")

    scripted_inputs = iter(
        [
            "Edit tests/fixtures/diff_accept_demo/calc.py and add divide() with guard.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert not any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    assert target.read_text(encoding="utf-8") == original
    snapshot = get_metrics_snapshot()
    assert snapshot.get("tool_mutation_blocked_total|reason=zero_code_blocks", 0) >= 1


def test_chat_multifile_edit_without_mutating_tool_emits_block_reason(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientCodeOnlyNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_CHAT_MAX_TOOL_STEPS", "4")

    a_file = tmp_path / "a.py"
    b_file = tmp_path / "b.py"
    a_file.write_text("x = 1\n", encoding="utf-8")
    b_file.write_text("y = 1\n", encoding="utf-8")

    scripted_inputs = iter(
        [
            "Edit a.py and b.py: add divide() and docstrings.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert not any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    snapshot = get_metrics_snapshot()
    assert snapshot.get("tool_mutation_blocked_total|reason=multiple_targets", 0) >= 1


def test_chat_prepare_stage_block_terminates_with_synth_prepare_blocked(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientCodeOnlyNoTools)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_CHAT_MAX_TOOL_STEPS", "4")

    scripted_inputs = iter(
        [
            "Edit /etc/hosts and add divide() with guard.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))

    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    reqs = list(_FakeChatClient.instances[-1]._requests.values())
    assert not any(str(r.get("tool_name")) == "fs_apply_patch" for r in reqs), result.output
    snapshot = get_metrics_snapshot()
    assert snapshot.get("tool_synth_write_blocked_total|reason=workspace_path_out_of_bounds", 0) >= 1
    assert snapshot.get("preprocess_rejected_synth_write|reason=workspace_path_out_of_bounds", 0) >= 1


def test_chat_surfaces_non_interactive_terminal_diff_block_reason(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeNoToolsPromptLog)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    def _reject_non_tty(*, path: str, patch_text: str, **_kwargs):
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "rejected"} for idx in range(parsed.hunks_total)],
            "all_accepted": False,
            "timed_out": False,
            "error": "non_tty",
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _reject_non_tty)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))
    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    inst = _FakeChatClient.instances[-1]
    assert any("edit blocked: non_interactive_terminal" in p for p in getattr(inst, "prompt_log", [])), result.output


def test_chat_surfaces_ide_bridge_unavailable_block_reason(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeNoToolsBridgeUnavailable)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    def _reject_generic(*, path: str, patch_text: str, **_kwargs):
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "rejected"} for idx in range(parsed.hunks_total)],
            "all_accepted": False,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _reject_generic)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))
    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    inst = _FakeChatClient.instances[-1]
    assert any("edit blocked: ide_bridge_unavailable" in p for p in getattr(inst, "prompt_log", [])), result.output


def test_chat_surfaces_malformed_diff_payload_block_reason(monkeypatch, tmp_path: Path):
    reset_metrics()
    _FakeChatClient.instances.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeChatClientReadThenCodeNoToolsMalformedDiff)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")

    target = tmp_path / "tests" / "fixtures" / "diff_accept_demo" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (
            "\"\"\"Dummy fixture for terminal diff accept/reject testing.\"\"\"\n\n"
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n"
            "def sub(a: float, b: float) -> float:\n"
            "    return a - b\n\n"
            "def mul(a: float, b: float) -> float:\n"
            "    return a * b\n"
        ),
        encoding="utf-8",
    )

    def _reject_generic(*, path: str, patch_text: str, **_kwargs):
        parsed = parse_unified_patch(patch_text)
        return {
            "file_path": path,
            "hunks_total": parsed.hunks_total,
            "decisions": [{"hunk_index": idx, "decision": "rejected"} for idx in range(parsed.hunks_total)],
            "all_accepted": False,
            "timed_out": False,
        }

    monkeypatch.setattr("openvegas.cli.review_patch_terminal", _reject_generic)
    scripted_inputs = iter(
        [
            "/approve allow",
            "Edit tests/fixtures/diff_accept_demo/calc.py: add divide(), add zero-division guard, and add docstrings to all functions.",
            "/exit",
        ]
    )
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(scripted_inputs))
    runner = CliRunner()
    result = runner.invoke(cli, ["chat"])
    assert result.exit_code == 0, result.output
    inst = _FakeChatClient.instances[-1]
    assert any("edit blocked: malformed_diff_payload" in p for p in getattr(inst, "prompt_log", [])), result.output
