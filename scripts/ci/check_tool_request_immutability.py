#!/usr/bin/env python3
"""Fail CI if immutable tool proposal fields are updated after creation."""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [ROOT / "openvegas", ROOT / "server"]
IMMUTABLE_COLUMNS = [
    "request_payload_json",
    "payload_hash",
    "execution_token",
]
UPDATE_RE = re.compile(r"update\s+agent_run_tool_calls\s+set\s+(.+?)where", re.IGNORECASE | re.DOTALL)


def _iter_source_files():
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if "migrations" in path.parts:
                continue
            yield path


def main() -> int:
    violations: list[str] = []
    for path in _iter_source_files():
        src = path.read_text(encoding="utf-8")
        for match in UPDATE_RE.finditer(src):
            set_clause = match.group(1).lower()
            for col in IMMUTABLE_COLUMNS:
                if col in set_clause:
                    violations.append(f"{path}: updates immutable column `{col}`")
    if violations:
        print("Tool request immutability check failed:", file=sys.stderr)
        for v in violations:
            print(f" - {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
