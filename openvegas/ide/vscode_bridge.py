"""Best-effort VSCode bridge adapter."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from openvegas.ide.bridge_types import IDEContext, ShowDiffResult
from openvegas.ide.show_diff import build_show_diff_result, read_text_best_effort


class VSCodeBridge:
    def __init__(self, workspace_root: str):
        self.workspace_root = str(Path(workspace_root).resolve())

    @staticmethod
    def _is_uri_path(path: str) -> bool:
        return "://" in path

    def _normalize_open_target(self, path: str) -> str:
        raw = str(path).strip()
        if self._is_uri_path(raw):
            return raw
        return str(Path(raw).resolve())

    async def open_file(self, path: str, line: int | None = None, col: int | None = None) -> None:
        code_bin = shutil.which("code")
        if not code_bin:
            raise RuntimeError("vscode launcher not available")
        target = self._normalize_open_target(path)
        if line is not None:
            goto = f"{target}:{max(1, int(line))}:{max(1, int(col or 1))}"
            proc = await asyncio.create_subprocess_exec(code_bin, "--goto", goto)
        else:
            proc = await asyncio.create_subprocess_exec(code_bin, target)
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError("editor_open_failed")

    async def run_command(self, command: str, terminal_name: str | None = None) -> None:
        code_bin = shutil.which("code")
        if not code_bin:
            raise RuntimeError("vscode launcher not available")
        args = [code_bin, "--command", command]
        if terminal_name:
            args.extend(["--reuse-window"])
        proc = await asyncio.create_subprocess_exec(*args)
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError("run_command_failed")

    async def show_diff(
        self, path: str, new_contents: str, allow_partial_accept: bool = True
    ) -> ShowDiffResult:
        current = "" if self._is_uri_path(path) else read_text_best_effort(path)
        return build_show_diff_result(
            path=path,
            current_contents=current,
            new_contents=new_contents,
            allow_partial_accept=allow_partial_accept,
        )

    async def get_open_files(self) -> list[str]:
        return []

    async def read_buffer(self, path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception:
            return None

    async def get_context(self) -> IDEContext:
        return {
            "open_files": [],
            "active_file": None,
            "cursor": None,
            "selection": None,
            "diagnostics": [],
            "terminal_history": [],
        }
