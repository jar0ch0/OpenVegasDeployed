#!/usr/bin/env python3
"""Fail CI if callback modules touch replay helpers/tables."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
CALLBACK_MODULES = [
    ROOT / "openvegas/agent/mutators/tool_start.py",
    ROOT / "openvegas/agent/mutators/tool_heartbeat.py",
    ROOT / "openvegas/agent/mutators/tool_result.py",
    ROOT / "openvegas/agent/mutators/tool_cancel.py",
    ROOT / "openvegas/agent/tool_cas.py",
]
BANNED_TOKENS = [
    "INSERT INTO agent_mutation_replays",
    "UPDATE agent_mutation_replays",
    "FROM agent_mutation_replays",
    "from openvegas.agent.replay",
    "import openvegas.agent.replay",
    "_claim_replay_processing_tx",
    "_complete_replay_tx",
    "_replay_preread",
]


def main() -> int:
    violations: list[str] = []
    for path in CALLBACK_MODULES:
        if not path.exists():
            violations.append(f"missing file: {path}")
            continue
        src = path.read_text(encoding="utf-8")
        for token in BANNED_TOKENS:
            if token in src:
                violations.append(f"{path}: contains forbidden token `{token}`")
    if violations:
        print("Callback/replay boundary check failed:", file=sys.stderr)
        for v in violations:
            print(f" - {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
