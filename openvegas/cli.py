"""OpenVegas CLI — Terminal Arcade for Developers."""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import re
import select
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from openvegas import __version__
from openvegas.agent.local_tools import (
    ToolExecutionResult,
    execute_shell_run_streaming,
    execute_tool_request,
    extract_tool_instruction,
    workspace_fingerprint,
)
from openvegas.agent.runtime_contracts import ToolPolicyDecision, evaluate_tool_policy
from openvegas.agent.runtime_contracts import result_submission_hash as compute_result_submission_hash
from openvegas.agent.tool_cas import redact_hash_truncate
from openvegas.config import load_config
from openvegas.ide.show_diff import normalize_show_diff_result
from openvegas.telemetry import emit_metric
from openvegas.tui.approval_menu import (
    ApprovalDecision,
    SessionApprovalState,
    action_scope_for,
    apply_approval_decision,
    approval_rules_summary,
    choose_approval,
    should_auto_allow,
)
from openvegas.tui.chat_theme import (
    normalize_approval_ui,
    normalize_chat_style,
    normalize_tool_event_density,
)
from openvegas.tui.chat_renderer import (
    render_assistant,
    render_status_bar,
    render_topup_hint,
    render_tool_event,
    render_tool_result,
    render_user_input,
)
from openvegas.tui.confetti import render_result_panel
from openvegas.tui.diff_reviewer import (
    ParsedUnifiedPatch,
    filter_patch_by_accepted_hunks as filter_patch_by_accepted_hunks_terminal,
    filtered_patch_footprint,
    is_valid_filtered_patch as is_valid_filtered_patch_terminal,
    parse_unified_patch as parse_unified_patch_terminal,
    review_patch_terminal,
)
from openvegas.tui.hints import verify_hint_for_result
from openvegas.tui.tool_event_renderer import describe_tool_action

console = Console()

SUPPORTED_TOOL_NAMES = {
    "fs_list",
    "fs_read",
    "fs_search",
    "fs_apply_patch",
    "shell_run",
    "editor_open",
}

EXTERNAL_TOOL_ALIASES = {
    "read": "fs_read",
    "search": "fs_search",
    "write": "fs_apply_patch",
    "bash": "shell_run",
    "list": "fs_list",
}
CANONICAL_EXTERNAL_TOOL_NAMES = tuple(sorted(EXTERNAL_TOOL_ALIASES.keys()))

RETRYABLE_MUTATION_ERRORS = {
    "stale_projection",
    "active_mutation_in_progress",
    "idempotency_conflict",
}


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_async(coro):
    """Run an async function from sync Click context."""
    return asyncio.run(coro)


def _drain_stdin_buffer(window_ms: int = 0) -> list[str]:
    """Drain unread stdin bytes that are already buffered.

    This prevents multiline paste leftovers from being consumed by the
    subsequent approval selector prompt.
    """
    if window_ms < 0:
        window_ms = 0
    try:
        if not sys.stdin.isatty():
            return []
        fd = sys.stdin.fileno()
    except Exception:
        return []

    deadline = time.monotonic() + (window_ms / 1000.0)
    chunks: list[bytes] = []
    while True:
        timeout = max(0.0, deadline - time.monotonic())
        if timeout <= 0.0 and window_ms > 0 and chunks:
            break
        if timeout <= 0.0 and window_ms == 0:
            timeout = 0.0
        try:
            ready, _, _ = select.select([fd], [], [], timeout)
        except Exception:
            break
        if not ready:
            break
        try:
            chunk = os.read(fd, 4096)
        except Exception:
            break
        if not chunk:
            break
        chunks.append(chunk)
        if window_ms == 0:
            # Immediate drain only for currently buffered bytes.
            continue
    if not chunks:
        return []
    text = b"".join(chunks).decode("utf-8", errors="ignore")
    return [ln.rstrip("\r") for ln in text.splitlines() if ln.rstrip("\r")]


def _path_hint_from_message(msg: str) -> str | None:
    text = (msg or "").strip()
    if not text:
        return None

    candidates: list[str] = []
    for pat in (
        r'"([^"\n]+)"',
        r"'([^'\n]+)'",
        r"`([^`\n]+)`",
    ):
        for m in re.finditer(pat, text):
            token = m.group(1).strip()
            if token:
                candidates.append(token)

    for candidate in re.findall(r"(/[^\s\"'`]+)", text):
        candidates.append(candidate.strip())

    for token in re.findall(r"(?<!\w)([A-Za-z0-9_.\-/]+)(?!\w)", text):
        t = token.strip(":;)]}>'\"`")
        if not t:
            continue
        if "/" in t or t.startswith(".") or "." in Path(t).name:
            candidates.append(t)

    seen: set[str] = set()
    fallback_nonexistent: str | None = None
    for candidate in candidates:
        c = candidate.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        p = Path(c)
        if p.exists():
            return str(p)
        if not p.is_absolute():
            local = Path.cwd() / p
            if local.exists():
                return str(p)
        # Keep a deterministic fallback even when file does not exist yet.
        if fallback_nonexistent is None and ("/" in c or c.startswith(".") or "." in p.name):
            fallback_nonexistent = c
    return fallback_nonexistent


def _search_pattern_hint_from_message(msg: str) -> str | None:
    text = (msg or "").strip()
    if not text:
        return None

    for pat in (
        r'"([^"\n]+)"',
        r"'([^'\n]+)'",
        r"`([^`\n]+)`",
        r"“([^”\n]+)”",
        r"‘([^’\n]+)’",
    ):
        m = re.search(pat, text)
        if m and m.group(1).strip():
            return m.group(1).strip()

    m = re.search(
        r"\b(?:search|find|grep|look\s+for)\b(?:\s+for)?\s+([^\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        raw = m.group(1).strip()
        raw = re.split(
            r"\b(?:across|in|within|under|inside|from|on)\b",
            raw,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" :;,.")
        if raw:
            return raw

    stop = {
        "search",
        "find",
        "grep",
        "across",
        "within",
        "repo",
        "repository",
        "codebase",
        "summarize",
        "where",
        "used",
        "talked",
        "about",
        "file",
        "this",
        "here",
        "what",
        "is",
        "the",
        "and",
    }
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.:-]{2,}", text):
        t = token.strip(".,:;")
        low = t.lower()
        if low in stop:
            continue
        if t.startswith("/"):
            continue
        return t
    return None


def _shell_command_hint_from_message(msg: str) -> str | None:
    text = (msg or "").strip()
    if not text:
        return None

    for pat in (r'"([^"\n]+)"', r"'([^'\n]+)'", r"`([^`\n]+)`"):
        m = re.search(pat, text)
        if m and m.group(1).strip():
            return m.group(1).strip()

    m = re.search(
        r"\b(?:run|execute)\s+(?:a\s+)?shell\s+command\b[:\s]+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        raw = m.group(1).strip()
        raw = re.split(r"\b(and|then)\b", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip(" :;,.")
        if raw:
            return raw
    return None


def _rewrite_shell_command_for_env(command: str) -> tuple[str, str | None]:
    cmd = str(command or "").strip()
    if not cmd:
        return cmd, None
    if shutil.which("rg") is None and re.match(r"^\s*rg\b", cmd):
        rewritten = re.sub(r"^\s*rg\b", "grep -R -n", cmd, count=1)
        return rewritten, "rg_unavailable_rewritten_to_grep"
    return cmd, None


def _coerce_nonempty_text(v: Any) -> str | None:
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return None


def _coerce_nonempty_text_preserve(v: Any) -> str | None:
    if isinstance(v, str) and v.strip():
        return v
    return None


def _mutation_retry_backoff_sec(error_code: str, attempt: int) -> float:
    code = str(error_code or "")
    idx = max(0, int(attempt))
    if code == "stale_projection":
        return 0.0
    if code == "active_mutation_in_progress":
        return min(0.5, 0.12 * (idx + 1))
    if code == "idempotency_conflict":
        return min(0.4, 0.08 * (idx + 1))
    return 0.0


def _safe_workspace_resolve(workspace_root: str, raw_path: str) -> Path | None:
    root = Path(workspace_root).resolve()
    p = Path(raw_path)
    target = (root / p).resolve() if not p.is_absolute() else p.resolve()
    if target == root or root in target.parents:
        return target
    return None


def _synthesize_patch_from_arguments(workspace_root: str, arguments: dict[str, Any]) -> str | None:
    path_val = None
    for key in ("path", "file_path", "filepath", "file", "target_path"):
        candidate = arguments.get(key)
        if isinstance(candidate, str) and candidate.strip():
            path_val = candidate.strip()
            break
        if isinstance(candidate, dict):
            nested = candidate.get("path")
            if isinstance(nested, str) and nested.strip():
                path_val = nested.strip()
                break
    if not path_val:
        return None

    new_text = None
    for key in ("new_content", "content", "after", "replacement", "updated_content", "text"):
        candidate = arguments.get(key)
        c = _coerce_nonempty_text(candidate)
        if c is not None:
            new_text = c
            break
    if new_text is None:
        return None

    target = _safe_workspace_resolve(workspace_root, path_val)
    if target is None:
        return None

    old_text: str = ""
    for key in ("old_content", "before", "original_content"):
        candidate = arguments.get(key)
        c = _coerce_nonempty_text(candidate)
        if c is not None:
            old_text = c
            break
    else:
        if target.exists() and target.is_file():
            try:
                old_text = target.read_text(encoding="utf-8")
            except Exception:
                return None

    root = Path(workspace_root).resolve()
    rel = str(target.relative_to(root))
    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=rel,
            tofile=rel,
            lineterm="",
        )
    )
    if not diff_lines:
        return None
    patch = "".join(line + ("\n" if not line.endswith("\n") else "") for line in diff_lines)
    return patch


def _canonical_tool_name(name: str) -> str:
    token = (name or "").strip().lower().replace("-", "_")
    aliases = {
        **EXTERNAL_TOOL_ALIASES,
        "read_file": "fs_read",
        "file_read": "fs_read",
        "cat_file": "fs_read",
        "list_files": "fs_list",
        "ls": "fs_list",
        "find_files": "fs_list",
        "grep": "fs_search",
        "search_code": "fs_search",
        "ripgrep": "fs_search",
        "rg_search": "fs_search",
        "create_file": "fs_apply_patch",
        "fs_create": "fs_apply_patch",
        "write_file": "fs_apply_patch",
        "file_write": "fs_apply_patch",
        "fs_write": "fs_apply_patch",
        "edit_file": "fs_apply_patch",
        "run_command": "shell_run",
        "execute_command": "shell_run",
        "terminal_run": "shell_run",
        "open_file": "editor_open",
    }
    return aliases.get(token, token)


def _tool_abi_mode() -> str:
    mode = os.getenv("OPENVEGAS_TOOL_ABI_MODE", "compat").strip().lower()
    if mode in {"strict", "compat"}:
        return mode
    return "compat"


def _terminal_diff_fallback_enabled() -> bool:
    raw = str(os.getenv("OPENVEGAS_TERMINAL_DIFF_FALLBACK", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _safe_rel_from_workspace(workspace_root: str, target: Path) -> str:
    root = Path(workspace_root).resolve()
    try:
        return str(target.relative_to(root))
    except Exception:
        return str(target)


def _read_existing_text_for_write(target: Path) -> tuple[str | None, str | None]:
    try:
        raw = target.read_bytes()
    except Exception as e:
        return None, f"Unable to read existing file: {e}"
    if b"\x00" in raw[:4096]:
        return None, "Existing file appears binary and cannot be rewritten via Write."
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "Existing file is not UTF-8 text and cannot be rewritten via Write."


def _build_unified_patch(*, old_text: str, new_text: str, rel_path: str) -> str | None:
    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=rel_path,
            tofile=rel_path,
            lineterm="",
        )
    )
    if not diff_lines:
        return None
    return "".join(line + ("\n" if not line.endswith("\n") else "") for line in diff_lines)


def _split_unified_patch_hunks(patch_text: str) -> tuple[list[str], list[list[str]]]:
    parsed = parse_unified_patch_terminal(patch_text)
    if parsed.parse_error:
        return [], []
    header: list[str] = []
    hunks: list[list[str]] = []
    for item in parsed.files:
        header.extend(item.prelude_lines)
        header.append(item.old_header)
        header.append(item.new_header)
        header.extend(item.metadata_lines)
        for hunk in item.hunks:
            hunks.append([hunk.header_line, *hunk.body_lines])
    return header, hunks


def _filter_patch_by_accepted_hunks(patch_text: str, accepted_hunks: set[int]) -> str | None:
    filtered_text, _ = _filter_patch_by_accepted_hunks_with_parsed(patch_text, accepted_hunks)
    return filtered_text


def _filter_patch_by_accepted_hunks_with_parsed(
    patch_text: str,
    accepted_hunks: set[int],
) -> tuple[str | None, ParsedUnifiedPatch | None]:
    return filter_patch_by_accepted_hunks_terminal(str(patch_text or ""), set(int(x) for x in accepted_hunks))


def _is_valid_filtered_patch(
    patch_text: str,
    *,
    parsed_patch: ParsedUnifiedPatch | None = None,
) -> bool:
    parsed = parsed_patch if parsed_patch is not None else parse_unified_patch_terminal(str(patch_text or ""))
    return is_valid_filtered_patch_terminal(parsed)


@dataclass(frozen=True)
class CompletionCriteria:
    required_files: tuple[str, ...] = ()
    required_headings: dict[str, tuple[str, ...]] = field(default_factory=dict)
    required_nonempty_sections: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(self.required_files or self.required_headings or self.required_nonempty_sections)


@dataclass(frozen=True)
class CompletionEvaluation:
    satisfied: bool
    missing: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class PatchHunk:
    file_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    touched_lines: int


@dataclass(frozen=True)
class PatchScope:
    targets: tuple[str, ...]
    hunks: tuple[PatchHunk, ...]
    touched_per_file: dict[str, int]
    touched_total: int
    hunk_count_per_file: dict[str, int]


@dataclass(frozen=True)
class HunkPair:
    original: PatchHunk
    regenerated: PatchHunk
    anchor_distance: int


@dataclass(frozen=True)
class HunkPairing:
    pairs: tuple[HunkPair, ...]
    deterministic: bool
    unmatched_original: int
    unmatched_regenerated: int


@dataclass(frozen=True)
class PairQuality:
    max_anchor_distance: int
    total_anchor_distance: int
    is_partial: bool


_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _normalize_diff_path(raw: str) -> str:
    token = str(raw or "").strip()
    if token.startswith("a/") or token.startswith("b/"):
        token = token[2:]
    return token


def _extract_required_files_from_message(user_message: str) -> list[str]:
    text = (user_message or "").strip()
    if not text:
        return []

    candidates: list[str] = []
    for pat in (r"`([^`\n]+)`", r'"([^"\n]+)"', r"'([^'\n]+)'"):
        for m in re.finditer(pat, text):
            token = m.group(1).strip()
            if "/" in token or "." in Path(token).name:
                candidates.append(token)

    for token in re.findall(r"(/[^\s\"'`]+)", text):
        candidates.append(token.strip())
    for token in re.findall(r"(?<!\w)([A-Za-z0-9_.\-/]+\.[A-Za-z0-9_]+)(?!\w)", text):
        candidates.append(token.strip())

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        c = candidate.strip(" \t\r\n:;,.")
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _extract_named_sections_from_message(user_message: str) -> list[str]:
    sections = _extract_sections_from_message(user_message)
    text = user_message or ""
    for pat in (
        r"\badd\s+a\s+[\"“]([^\"”\n]+)[\"”]\s+section\b",
        r"\badd\s+a\s+`([^`\n]+)`\s+section\b",
    ):
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            token = m.group(1).strip()
            if token:
                sections.append(token)
    out: list[str] = []
    seen: set[str] = set()
    for item in sections:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def _build_completion_criteria(user_message: str) -> CompletionCriteria:
    files = _extract_required_files_from_message(user_message)
    sections = _extract_named_sections_from_message(user_message)
    if not files and not sections:
        return CompletionCriteria()

    required_files = tuple(files)
    required_headings: dict[str, tuple[str, ...]] = {}
    required_nonempty: dict[str, tuple[str, ...]] = {}
    if sections and files:
        primary = files[0]
        required_headings[primary] = tuple(sections)
        required_nonempty[primary] = tuple(sections)
    return CompletionCriteria(
        required_files=required_files,
        required_headings=required_headings,
        required_nonempty_sections=required_nonempty,
    )


def _resolve_under_workspace(workspace_root: str, path_token: str) -> Path | None:
    return _safe_workspace_resolve(workspace_root, path_token)


def _parse_markdown_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _evaluate_completion_criteria(criteria: CompletionCriteria, workspace_root: str) -> CompletionEvaluation:
    if not criteria.active:
        return CompletionEvaluation(satisfied=True, missing=(), fingerprint="none")

    missing: list[str] = []
    file_state: dict[str, str] = {}
    sections_cache: dict[str, dict[str, str]] = {}

    for file_token in criteria.required_files:
        target = _resolve_under_workspace(workspace_root, file_token)
        if target is None:
            missing.append(f"{file_token}:out_of_bounds")
            continue
        if not target.exists() or not target.is_file():
            missing.append(f"{file_token}:missing")
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except Exception:
            missing.append(f"{file_token}:unreadable")
            continue
        file_state[file_token] = _sha256_hex(content.encode("utf-8"))
        sections_cache[file_token] = _parse_markdown_sections(content)

    for file_token, headings in criteria.required_headings.items():
        sections = sections_cache.get(file_token, {})
        section_keys = {k.lower(): k for k in sections.keys()}
        for heading in headings:
            if heading.lower() not in section_keys:
                missing.append(f"{file_token}:heading:{heading}")

    for file_token, headings in criteria.required_nonempty_sections.items():
        sections = sections_cache.get(file_token, {})
        section_keys = {k.lower(): k for k in sections.keys()}
        for heading in headings:
            key = section_keys.get(heading.lower())
            if not key:
                continue
            if not sections.get(key, "").strip():
                missing.append(f"{file_token}:empty:{heading}")

    fp_payload = {
        "missing": sorted(missing),
        "file_state": file_state,
    }
    fingerprint = _sha256_hex(json.dumps(fp_payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return CompletionEvaluation(
        satisfied=(len(missing) == 0),
        missing=tuple(sorted(missing)),
        fingerprint=fingerprint,
    )


def _parse_patch_scope(patch_text: str) -> PatchScope | None:
    text = str(patch_text or "")
    if not text.strip():
        return None
    lines = text.splitlines()
    current_file: str | None = None
    hunks: list[PatchHunk] = []
    touched_per_file: dict[str, int] = {}
    hunk_count_per_file: dict[str, int] = {}

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("+++ "):
            current_file = _normalize_diff_path(line[4:].strip())
            idx += 1
            continue
        if line.startswith("@@"):
            m = _HUNK_HEADER_RE.match(line)
            if not m or not current_file or current_file == "/dev/null":
                return None
            old_start = int(m.group(1))
            old_count = int(m.group(2) or "1")
            new_start = int(m.group(3))
            new_count = int(m.group(4) or "1")
            touched = 0
            idx += 1
            while idx < len(lines) and not lines[idx].startswith("@@") and not lines[idx].startswith("--- ") and not lines[idx].startswith("+++ "):
                body_line = lines[idx]
                if body_line.startswith("+") or body_line.startswith("-"):
                    touched += 1
                idx += 1
            touched = max(1, touched)
            hunk = PatchHunk(
                file_path=current_file,
                old_start=old_start,
                old_count=max(1, old_count),
                new_start=new_start,
                new_count=max(1, new_count),
                touched_lines=touched,
            )
            hunks.append(hunk)
            touched_per_file[current_file] = touched_per_file.get(current_file, 0) + touched
            hunk_count_per_file[current_file] = hunk_count_per_file.get(current_file, 0) + 1
            continue
        idx += 1

    if not hunks:
        return None
    targets = tuple(sorted(touched_per_file.keys()))
    touched_total = sum(touched_per_file.values())
    return PatchScope(
        targets=targets,
        hunks=tuple(hunks),
        touched_per_file=touched_per_file,
        touched_total=touched_total,
        hunk_count_per_file=hunk_count_per_file,
    )


def _pair_hunks_by_file_order_nearest(original: PatchScope, regenerated: PatchScope) -> HunkPairing:
    orig_by_file: dict[str, list[PatchHunk]] = {}
    regen_by_file: dict[str, list[PatchHunk]] = {}
    for h in original.hunks:
        orig_by_file.setdefault(h.file_path, []).append(h)
    for h in regenerated.hunks:
        regen_by_file.setdefault(h.file_path, []).append(h)

    pairs: list[HunkPair] = []
    deterministic = True
    unmatched_original = 0
    unmatched_regenerated = 0

    for file_path, orig_hunks in orig_by_file.items():
        regen_hunks = regen_by_file.get(file_path, [])
        used: set[int] = set()
        for orig in orig_hunks:
            candidates: list[tuple[int, int, PatchHunk]] = []
            for idx, regen in enumerate(regen_hunks):
                if idx in used:
                    continue
                distance = abs(orig.old_start - regen.old_start)
                candidates.append((distance, idx, regen))
            if not candidates:
                unmatched_original += 1
                deterministic = False
                continue
            candidates.sort(key=lambda item: (item[0], item[1]))
            if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
                deterministic = False
            best_distance, best_idx, best_hunk = candidates[0]
            used.add(best_idx)
            pairs.append(HunkPair(original=orig, regenerated=best_hunk, anchor_distance=best_distance))
        unmatched_regenerated += max(0, len(regen_hunks) - len(used))

    for file_path, regen_hunks in regen_by_file.items():
        if file_path not in orig_by_file:
            unmatched_regenerated += len(regen_hunks)

    return HunkPairing(
        pairs=tuple(pairs),
        deterministic=deterministic,
        unmatched_original=unmatched_original,
        unmatched_regenerated=unmatched_regenerated,
    )


def _pairing_quality(pairing: HunkPairing) -> PairQuality:
    max_distance = max((p.anchor_distance for p in pairing.pairs), default=0)
    total_distance = sum(p.anchor_distance for p in pairing.pairs)
    is_partial = (len(pairing.pairs) == 0) or (pairing.unmatched_original > 0) or (not pairing.deterministic)
    return PairQuality(
        max_anchor_distance=max_distance,
        total_anchor_distance=total_distance,
        is_partial=is_partial,
    )


def _hunks_within_drift(pairing: HunkPairing, tolerance: int) -> bool:
    tol = max(0, int(tolerance))
    for pair in pairing.pairs:
        orig_end = pair.original.old_start + max(1, pair.original.old_count) - 1
        regen_end = pair.regenerated.old_start + max(1, pair.regenerated.old_count) - 1
        if abs(pair.original.old_start - pair.regenerated.old_start) > tol:
            return False
        if abs(orig_end - regen_end) > tol:
            return False
    return True


def _has_hunks_outside_original_regions(
    original: PatchScope,
    regenerated: PatchScope,
    *,
    tolerance: int,
) -> bool:
    tol = max(0, int(tolerance))
    original_by_file: dict[str, list[PatchHunk]] = {}
    for h in original.hunks:
        original_by_file.setdefault(h.file_path, []).append(h)

    for h in regenerated.hunks:
        originals = original_by_file.get(h.file_path, [])
        if not originals:
            return True
        regen_start = h.old_start
        regen_end = h.old_start + max(1, h.old_count) - 1
        inside_any = False
        for orig in originals:
            orig_start = orig.old_start - tol
            orig_end = orig.old_start + max(1, orig.old_count) - 1 + tol
            if regen_end >= orig_start and regen_start <= orig_end:
                inside_any = True
                break
        if not inside_any:
            return True
    return False


def _validate_patch_recovery_scope(
    *,
    original_patch: str,
    regenerated_patch: str,
    drift_tolerance_lines: int = 8,
    scope_multiplier: float = 2.0,
    absolute_slack_lines: int = 12,
    pair_max_anchor_distance_lines: int = 8,
    pair_quality_max_total_distance: int = 20,
) -> str | None:
    original = _parse_patch_scope(original_patch)
    regenerated = _parse_patch_scope(regenerated_patch)
    if original is None or regenerated is None:
        return "patch_recovery_scope_expansion"

    if set(original.targets) != set(regenerated.targets):
        return "patch_recovery_scope_expansion"

    pairing = _pair_hunks_by_file_order_nearest(original, regenerated)
    quality = _pairing_quality(pairing)
    if quality.is_partial:
        return "patch_recovery_scope_expansion"
    if quality.max_anchor_distance > max(0, int(pair_max_anchor_distance_lines)):
        return "patch_recovery_scope_expansion"
    if quality.total_anchor_distance > max(0, int(pair_quality_max_total_distance)):
        return "patch_recovery_scope_expansion"

    for file_path in original.targets:
        original_touched = int(original.touched_per_file.get(file_path, 0))
        regenerated_touched = int(regenerated.touched_per_file.get(file_path, 0))
        allowed = max(
            int(original_touched * float(scope_multiplier)),
            int(original_touched + int(absolute_slack_lines)),
        )
        if regenerated_touched > allowed:
            return "patch_recovery_scope_expansion"

    allowed_total = max(
        int(original.touched_total * float(scope_multiplier)),
        int(original.touched_total + int(absolute_slack_lines)),
    )
    if regenerated.touched_total > allowed_total:
        return "patch_recovery_scope_expansion"

    if not _hunks_within_drift(pairing, tolerance=int(drift_tolerance_lines)):
        return "patch_recovery_scope_expansion"

    if _has_hunks_outside_original_regions(
        original,
        regenerated,
        tolerance=int(drift_tolerance_lines),
    ):
        return "patch_recovery_scope_expansion"

    return None


def _truncate_text(text: str, limit: int = 800) -> str:
    raw = str(text or "")
    if len(raw) <= max(0, int(limit)):
        return raw
    return raw[: max(0, int(limit))] + "...<truncated>"


def _tool_result_reason_code(result: ToolExecutionResult) -> str:
    payload = result.result_payload if isinstance(result.result_payload, dict) else {}
    code = payload.get("patch_failure_code") or payload.get("reason_code") or payload.get("error")
    token = str(code or "").strip()
    return token or "tool_execution_failed"


def _patch_recovery_payload(
    *,
    reason_code: str,
    detail: str,
    original_outcome: ToolExecutionResult,
    retry_outcome: ToolExecutionResult | None,
    original_patch: str,
    regenerated_patch: str,
    scope_guard_rejected: bool = False,
    scope_guard_subreason: str | None = None,
) -> dict[str, Any]:
    original_payload = original_outcome.result_payload if isinstance(original_outcome.result_payload, dict) else {}
    retry_payload = (
        retry_outcome.result_payload
        if isinstance(retry_outcome, ToolExecutionResult) and isinstance(retry_outcome.result_payload, dict)
        else {}
    )
    original_scope = _parse_patch_scope(original_patch)
    regenerated_scope = _parse_patch_scope(regenerated_patch)
    target_files = sorted(
        set((original_scope.targets if original_scope is not None else ()))
        | set((regenerated_scope.targets if regenerated_scope is not None else ()))
    )
    return {
        "ok": False,
        "reason_code": reason_code,
        "detail": detail,
        "original_reason_code": str(
            original_payload.get("patch_failure_code")
            or original_payload.get("reason_code")
            or original_payload.get("error")
            or "tool_execution_failed"
        ),
        "retry_reason_code": (
            str(
                retry_payload.get("patch_failure_code")
                or retry_payload.get("reason_code")
                or retry_payload.get("error")
                or ""
            ).strip()
            or None
        ),
        "scope_guard_rejected": bool(scope_guard_rejected),
        "scope_guard_subreason": scope_guard_subreason,
        "target_files": target_files,
        "hunk_count": int(len(original_scope.hunks) if original_scope is not None else 0),
        "original_patch_sha256": _sha256_hex(str(original_patch).encode("utf-8")),
        "regenerated_patch_sha256": _sha256_hex(str(regenerated_patch).encode("utf-8")),
        "original_stdout": _truncate_text(original_outcome.stdout or ""),
        "original_stderr": _truncate_text(original_outcome.stderr or ""),
        "retry_stdout": _truncate_text((retry_outcome.stdout if retry_outcome is not None else "") or ""),
        "retry_stderr": _truncate_text((retry_outcome.stderr if retry_outcome is not None else "") or ""),
        "original_patch_diagnostics": (
            original_payload.get("patch_diagnostics") if isinstance(original_payload.get("patch_diagnostics"), dict) else None
        ),
        "retry_patch_diagnostics": (
            retry_payload.get("patch_diagnostics") if isinstance(retry_payload.get("patch_diagnostics"), dict) else None
        ),
    }


def _is_artifact_whole_file_fallback_target(*, rel_path: str, new_contents: str) -> bool:
    p = Path(str(rel_path or "").strip())
    if not p or p.is_absolute():
        return False
    # Keep fallback narrow: root-level artifact files only (never source tree writes).
    if len(p.parts) != 1 or any(part in {"..", "."} for part in p.parts):
        return False
    suffix = p.suffix.lower()
    allowed = {".md", ".txt", ".rst", ".log"}
    if suffix not in allowed:
        return False
    max_bytes = max(1024, int(os.getenv("OPENVEGAS_BOOTSTRAP_WRITE_MAX_BYTES", "262144")))
    return len((new_contents or "").encode("utf-8")) <= max_bytes


def _attempt_bootstrap_write_fallback(
    *,
    workspace_root: str,
    rel_path: str,
    new_contents: str,
    existing_file: bool,
) -> ToolExecutionResult | None:
    del existing_file
    if not _is_artifact_whole_file_fallback_target(
        rel_path=str(rel_path or ""),
        new_contents=str(new_contents or ""),
    ):
        return None
    target = _safe_workspace_resolve(workspace_root, str(rel_path or ""))
    if target is None:
        return ToolExecutionResult(
            "failed",
            {
                "ok": False,
                "reason_code": "workspace_path_out_of_bounds",
                "detail": "Bootstrap fallback target is outside workspace root.",
            },
            "",
            "",
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(new_contents or ""), encoding="utf-8")
    except Exception as e:
        return ToolExecutionResult(
            "failed",
            {
                "ok": False,
                "reason_code": "patch_recovery_failed_bootstrap_fallback_exhausted",
                "detail": f"Bootstrap whole-file fallback failed: {e}",
            },
            "",
            "",
        )
    return ToolExecutionResult(
        "succeeded",
        {
            "ok": True,
            "fallback_mode": "bootstrap_whole_file",
            "path": str(rel_path or ""),
            "bytes_written": len(str(new_contents or "").encode("utf-8")),
            "detail": "Bootstrap whole-file fallback write succeeded.",
        },
        "",
        "",
    )


def _patch_failure_signature(
    *,
    arguments: dict[str, Any],
    write_meta: dict[str, Any] | None,
    outcome: ToolExecutionResult,
) -> str:
    patch_text = str(arguments.get("patch", ""))
    scope = _parse_patch_scope(patch_text)
    payload = outcome.result_payload if isinstance(outcome.result_payload, dict) else {}
    filtered_targets: list[str] = []
    filtered_hunk_total: int | None = None
    filtered_touched: dict[str, int] | None = None
    if isinstance(write_meta, dict):
        raw_targets = write_meta.get("filtered_target_files")
        if isinstance(raw_targets, list):
            filtered_targets = [str(x) for x in raw_targets if str(x).strip()]
        try:
            if write_meta.get("filtered_hunks_total") is not None:
                filtered_hunk_total = int(write_meta.get("filtered_hunks_total"))
        except Exception:
            filtered_hunk_total = None
        if isinstance(write_meta.get("filtered_touched_per_file"), dict):
            filtered_touched = {
                str(k): int(v)
                for k, v in dict(write_meta.get("filtered_touched_per_file")).items()
                if str(k).strip()
            }
    base = {
        "reason_code": _tool_result_reason_code(outcome),
        "target_files": (
            sorted(filtered_targets)
            if filtered_targets
            else (list(scope.targets) if scope is not None else [])
        ),
        "hunk_count": (
            int(filtered_hunk_total)
            if filtered_hunk_total is not None
            else int(len(scope.hunks) if scope is not None else 0)
        ),
        "patch_sha256": _sha256_hex(patch_text.encode("utf-8")),
        "stderr_sha256": _sha256_hex(str(outcome.stderr or "").encode("utf-8")),
    }
    if filtered_touched:
        base["touched_per_file"] = filtered_touched
    if isinstance(write_meta, dict):
        base["write_path"] = str(write_meta.get("path") or "")
        base["existing_file"] = bool(write_meta.get("existing_file"))
        new_contents = str(write_meta.get("new_contents") or "")
        base["new_contents_sha256"] = _sha256_hex(new_contents.encode("utf-8"))
    if isinstance(payload.get("patch_diagnostics"), dict):
        base["patch_failure_code"] = str(payload.get("patch_failure_code") or "")
    return _sha256_hex(json.dumps(base, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def _prepare_write_patch(
    *,
    workspace_root: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    path = _coerce_nonempty_text(arguments.get("filepath")) or _coerce_nonempty_text(arguments.get("path"))
    if path is None:
        path = _deep_find_keyed_string(arguments, ("filepath", "path", "file_path", "file", "target_path"))
    content: str | None = None
    raw_content = arguments.get("content")
    if isinstance(raw_content, str):
        content = raw_content
    if content is None:
        raw_new_content = arguments.get("new_content")
        if isinstance(raw_new_content, str):
            content = raw_new_content
    if content is None:
        content = _deep_find_keyed_string(arguments, ("content", "new_content", "text", "replacement", "value"))

    if not path or content is None:
        return None, {
            "status": "blocked",
            "error": "invalid_tool_arguments",
            "detail": "Write requires filepath and content.",
        }

    target = _safe_workspace_resolve(workspace_root, path)
    if target is None:
        return None, {
            "status": "blocked",
            "error": "workspace_path_out_of_bounds",
            "detail": "Write target is outside workspace root.",
        }

    exists = target.exists()
    if exists and not target.is_file():
        return None, {
            "status": "blocked",
            "error": "invalid_tool_arguments",
            "detail": "Write target must be a file.",
        }

    rel_path = _safe_rel_from_workspace(workspace_root, target)
    old_text = ""
    if exists:
        loaded, err = _read_existing_text_for_write(target)
        if err is not None:
            return None, {
                "status": "blocked",
                "error": "binary_file_unsupported",
                "detail": err,
            }
        old_text = loaded or ""
        if old_text == content:
            return None, {
                "status": "noop",
                "tool_name": "fs_apply_patch",
                "error": "no_change",
                "detail": "Write produced no changes.",
            }

    patch = _build_unified_patch(old_text=old_text, new_text=content, rel_path=rel_path)
    if patch is None:
        return None, {
            "status": "noop",
            "tool_name": "fs_apply_patch",
            "error": "no_change",
            "detail": "Write produced no changes.",
        }

    prepared = {
        "patch": patch,
        "path": rel_path,
    }
    meta = {
        "source": "write_abi",
        "path": rel_path,
        "new_contents": content,
        "existing_file": bool(exists),
    }
    return {"arguments": prepared, "meta": meta}, None


def _has_patch_intent(msg: str) -> bool:
    text = (msg or "").lower()
    if re.search(r"\b(patch|edit|modify|update|change)\b", text):
        return True
    if re.search(r"\b(create|write|append|overwrite)\b", text) and (
        "file" in text or bool(re.search(r"[A-Za-z0-9_.\-/]+\.[A-Za-z0-9_]+", text))
    ):
        return True
    return False


def _is_patch_repeat_followup_intent(msg: str) -> bool:
    text = (msg or "").lower().strip()
    return bool(re.search(r"^(?:apply\s+)?(?:another(?:\s+one)?|one\s+more|again)\b", text))


def _has_explicit_file_target(msg: str) -> bool:
    text = (msg or "").strip()
    if not text:
        return False
    if re.search(r"(/[^\s\"'`]+)", text):
        return True
    # common file-like tokens
    if re.search(r"\b[\w.\-]+\.(py|ts|tsx|js|jsx|md|json|yaml|yml|sql|toml|txt|rs|go|java|kt|cpp|c|h)\b", text, flags=re.IGNORECASE):
        return True
    return False


def _is_temp_patch_smoke_intent(msg: str) -> bool:
    text = (msg or "").lower()
    return _has_patch_intent(text) and bool(re.search(r"\b(temp|temporary)\s+file\b", text))


def _is_patch_smoke_intent(msg: str) -> bool:
    text = (msg or "").lower().strip()
    if not _has_patch_intent(text):
        return False
    if _is_temp_patch_smoke_intent(text):
        return True
    if re.search(r"\b(another|one more)\s+patch\b", text) and not _has_explicit_file_target(text):
        return True
    if re.search(r"\btiny\s+patch\b", text) and not _has_explicit_file_target(text):
        return True
    return False


def _is_file_create_intent(msg: str) -> bool:
    text = (msg or "").lower().strip()
    has_create_verb = bool(re.search(r"\b(create|make|write|generate)\b", text))
    if not has_create_verb:
        return False
    if "file" in text:
        return True
    if _has_explicit_file_target(text):
        return True
    return False


def _extract_sections_from_message(msg: str) -> list[str]:
    text = (msg or "").strip()
    if not text:
        return []
    m = re.search(r"\bsections?\s*:\s*([^\n\r.]+)", text, flags=re.IGNORECASE)
    if not m:
        return []
    raw = m.group(1)
    parts = [p.strip() for p in re.split(r",|\band\b", raw, flags=re.IGNORECASE) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        token = p.strip("`'\" ")
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _create_file_fallback_args(user_message: str) -> dict[str, Any]:
    target = _path_hint_from_message(user_message) or ".openvegas_tmp_patch.txt"
    sections = _extract_sections_from_message(user_message)
    if sections and str(target).lower().endswith(".md"):
        title = Path(str(target)).name.lstrip(".") or "temp"
        lines = [f"# {title}", ""]
        for section in sections:
            lines.extend([f"## {section}", ""])
        new_content = "\n".join(lines).rstrip() + "\n"
    elif sections:
        new_content = "\n".join([f"[{s}]" for s in sections]) + "\n"
    else:
        new_content = ""
    return {
        "path": target,
        "new_content": new_content,
    }


def _tool_debug_enabled() -> bool:
    return os.getenv("OPENVEGAS_TOOL_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def _tool_debug(message: str) -> None:
    if _tool_debug_enabled():
        console.print(f"[dim][tool-debug][/dim] {message}")


def _promote_tool_call_for_patch_intent(
    *,
    user_message: str,
    tool_name: str,
    arguments: dict[str, Any],
    tool_observations: list[dict[str, Any]],
    force_patch_intent: bool = False,
) -> tuple[str, dict[str, Any]]:
    def _fallback_args() -> dict[str, Any]:
        suffix = uuid.uuid4().hex[:8]
        return {
            "path": ".openvegas_tmp_patch.txt",
            "new_content": f"openvegas temp patch applied {suffix}\n",
        }

    patch_smoke_intent = force_patch_intent or _is_patch_smoke_intent(user_message)
    create_file_intent = _is_file_create_intent(user_message)
    if not (patch_smoke_intent or create_file_intent):
        return tool_name, arguments
    already_patch_attempted = any(str(o.get("tool_name")) == "fs_apply_patch" for o in tool_observations)
    if already_patch_attempted:
        return tool_name, arguments
    if create_file_intent:
        if tool_name not in SUPPORTED_TOOL_NAMES:
            return "fs_apply_patch", _create_file_fallback_args(user_message)
        if tool_name in {"fs_list", "fs_read", "fs_search", "editor_open"}:
            return "fs_apply_patch", _create_file_fallback_args(user_message)
        return tool_name, arguments
    if tool_name not in SUPPORTED_TOOL_NAMES:
        return "fs_apply_patch", _fallback_args()
    if tool_name != "fs_list":
        return tool_name, arguments
    return "fs_apply_patch", _fallback_args()


def _synth_patch_tool_req_for_intent(
    *,
    user_message: str,
    tool_observations: list[dict[str, Any]],
    force_patch_intent: bool = False,
) -> dict[str, Any] | None:
    patch_smoke_intent = force_patch_intent or _is_patch_smoke_intent(user_message)
    create_file_intent = _is_file_create_intent(user_message)
    if not (patch_smoke_intent or create_file_intent):
        return None
    if any(str(o.get("tool_name")) == "fs_apply_patch" for o in tool_observations):
        return None
    if create_file_intent:
        args = _create_file_fallback_args(user_message)
        return {
            "type": "tool_call",
            "tool_name": "fs_apply_patch",
            "arguments": args,
            "shell_mode": "mutating",
            "timeout_sec": 30,
        }
    suffix = uuid.uuid4().hex[:8]
    return {
        "type": "tool_call",
        "tool_name": "fs_apply_patch",
        "arguments": {
            "path": ".openvegas_tmp_patch.txt",
            "new_content": f"openvegas temp patch applied {suffix}\n",
        },
        "shell_mode": "mutating",
        "timeout_sec": 30,
    }


def _deep_find_keyed_string(v: Any, keys: tuple[str, ...], depth: int = 0) -> str | None:
    if depth > 4:
        return None
    if isinstance(v, dict):
        for k in keys:
            if k in v:
                hit = _coerce_nonempty_text(v.get(k))
                if hit:
                    return hit
                hit = _deep_find_keyed_string(v.get(k), keys, depth + 1)
                if hit:
                    return hit
        for child in v.values():
            hit = _deep_find_keyed_string(child, keys, depth + 1)
            if hit:
                return hit
    elif isinstance(v, list):
        for child in v:
            hit = _deep_find_keyed_string(child, keys, depth + 1)
            if hit:
                return hit
    return None


def _collect_tool_call_candidates(tool_calls_payload: Any, fallback_text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(tool_calls_payload, list):
        for item in tool_calls_payload:
            if not isinstance(item, dict):
                continue
            if item.get("tool_name"):
                args = item.get("arguments", {})
                if isinstance(args, str):
                    try:
                        parsed_args = json.loads(args)
                        args = parsed_args if isinstance(parsed_args, dict) else {}
                    except Exception:
                        args = {}
                if not isinstance(args, dict):
                    args = {}
                candidates.append(
                    {
                        "type": "tool_call",
                        "tool_name": item.get("tool_name"),
                        "arguments": args,
                        "shell_mode": item.get("shell_mode", "read_only"),
                        "timeout_sec": item.get("timeout_sec", 30),
                    }
                )
                continue

            fn = item.get("function")
            if not isinstance(fn, dict):
                continue
            fn_name = str(fn.get("name") or "").strip()
            raw_args = fn.get("arguments", {})
            parsed: dict[str, Any] = {}
            if isinstance(raw_args, str):
                try:
                    loaded = json.loads(raw_args)
                    parsed = loaded if isinstance(loaded, dict) else {}
                except Exception:
                    parsed = {}
            elif isinstance(raw_args, dict):
                parsed = raw_args
            tool_name = str(parsed.get("tool_name") or "").strip()
            if not tool_name and fn_name:
                tool_name = fn_name
            if not tool_name:
                continue
            args_obj = parsed.get("arguments", {})
            if not isinstance(args_obj, dict):
                args_obj = {}
            if not args_obj:
                # Native function-call payloads may place arguments at the top level.
                top_level = {k: v for k, v in parsed.items() if k not in {"tool_name", "shell_mode", "timeout_sec"}}
                if isinstance(top_level, dict) and top_level:
                    args_obj = top_level
            candidates.append(
                {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "arguments": args_obj,
                    "shell_mode": parsed.get("shell_mode", "read_only"),
                    "timeout_sec": parsed.get("timeout_sec", 30),
                }
            )

    if candidates:
        return candidates

    fallback_req, _ = extract_tool_instruction(fallback_text)
    if isinstance(fallback_req, dict):
        candidates.append(fallback_req)
    return candidates


def _semantic_tool_signature(tool_name: str, arguments: dict[str, Any], shell_mode: str | None) -> str:
    name = str(tool_name).strip()
    args = arguments or {}
    if name in {"fs_read", "editor_open"}:
        key = {"tool_name": name, "path": str(args.get("path", "")).strip()}
    elif name == "fs_list":
        key = {
            "tool_name": name,
            "path": str(args.get("path", ".")).strip() or ".",
            "recursive": bool(args.get("recursive", False)),
        }
    elif name == "fs_search":
        key = {
            "tool_name": name,
            "path": str(args.get("path", ".")).strip() or ".",
            "pattern": str(args.get("pattern", "")).strip(),
        }
    elif name == "fs_apply_patch":
        key = {
            "tool_name": name,
            "patch": str(args.get("patch", "")).strip(),
        }
    elif name == "shell_run":
        key = {
            "tool_name": name,
            "shell_mode": str(shell_mode or "read_only"),
            "command": str(args.get("command", "")).strip(),
        }
    else:
        key = {"tool_name": name, "arguments": args}
    return json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _preprocess_tool_request_for_runtime(
    *,
    tool_req: dict[str, Any],
    user_message: str,
    model_text: str,
    workspace_root: str,
    tool_observations: list[dict[str, Any]],
    force_patch_intent: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    tool_name_raw = str(tool_req.get("tool_name", "")).strip()
    raw_token = tool_name_raw.lower().replace("-", "_")
    if tool_name_raw and _tool_abi_mode() == "strict":
        if raw_token not in CANONICAL_EXTERNAL_TOOL_NAMES:
            return None, {
                "tool_name": tool_name_raw,
                "status": "blocked",
                "error": "invalid_tool_arguments",
                "detail": (
                    "Non-canonical tool name is rejected in strict ABI mode. "
                    f"Use one of {list(CANONICAL_EXTERNAL_TOOL_NAMES)}."
                ),
            }
    tool_name = _canonical_tool_name(tool_name_raw)
    emit_metric(
        "tool_name_canonical_seen_total",
        {
            "tool_name_raw": tool_name_raw or "(missing)",
            "tool_name_canonical": tool_name or "(missing)",
        },
    )
    if tool_name_raw and tool_name_raw != tool_name:
        emit_metric(
            "tool_alias_rewrite_total",
            {
                "tool_name_raw": tool_name_raw,
                "tool_name_canonical": tool_name,
            },
        )
    arguments = tool_req.get("arguments")
    if isinstance(arguments, str):
        try:
            parsed_args = json.loads(arguments)
            arguments = parsed_args if isinstance(parsed_args, dict) else {}
        except Exception:
            arguments = {}
    if not isinstance(arguments, dict):
        return None, {
            "tool_name": tool_name_raw or tool_name,
            "status": "blocked",
            "error": "invalid_tool_arguments",
            "detail": "Tool arguments must be an object.",
        }

    pre_promote_tool_name = tool_name
    tool_name, arguments = _promote_tool_call_for_patch_intent(
        user_message=user_message,
        tool_name=tool_name,
        arguments=dict(arguments),
        tool_observations=tool_observations,
        force_patch_intent=force_patch_intent,
    )
    if pre_promote_tool_name != tool_name:
        emit_metric(
            "tool_fallback_promotion_total",
            {"from_tool": pre_promote_tool_name, "to_tool": tool_name},
        )

    if tool_name not in SUPPORTED_TOOL_NAMES:
        return None, {
            "tool_name": tool_name_raw or tool_name,
            "status": "blocked",
            "error": "unknown_tool_name",
            "detail": f"Unsupported tool `{tool_name_raw}`; use one of {sorted(SUPPORTED_TOOL_NAMES)}.",
        }

    write_like_request = (
        str(tool_name_raw or "").strip().lower() in {"write", "write_file", "file_write"}
        or (
            tool_name == "fs_apply_patch"
            and _coerce_nonempty_text(arguments.get("filepath")) is not None
            and (
                isinstance(arguments.get("content"), str)
                or isinstance(arguments.get("new_content"), str)
            )
            and _coerce_nonempty_text(arguments.get("patch")) is None
        )
    )

    if write_like_request:
        write_prepared, write_err = _prepare_write_patch(workspace_root=workspace_root, arguments=arguments)
        if write_err is not None:
            err = {
                "tool_name": tool_name,
                "status": write_err.get("status", "blocked"),
                "error": write_err.get("error", "invalid_tool_arguments"),
                "detail": write_err.get("detail", "Write preprocessing failed."),
            }
            return None, err
        assert write_prepared is not None
        arguments = dict(write_prepared["arguments"])
        write_meta = dict(write_prepared["meta"])
    else:
        write_meta = None

    if tool_name in {"fs_read", "editor_open"}:
        if not (isinstance(arguments.get("path"), str) and str(arguments.get("path")).strip()):
            alias_path = _deep_find_keyed_string(
                arguments,
                ("path", "file_path", "filepath", "file", "target_path", "filename", "name"),
            )
            if alias_path:
                arguments["path"] = alias_path
        if not (isinstance(arguments.get("path"), str) and str(arguments.get("path")).strip()):
            hint = _path_hint_from_message(user_message) or _path_hint_from_message(model_text)
            if hint:
                arguments["path"] = hint

    if tool_name == "fs_search":
        pattern = arguments.get("pattern")
        if isinstance(pattern, dict):
            pattern = _deep_find_keyed_string(pattern, ("pattern", "query", "text", "value"))
        if not (isinstance(pattern, str) and pattern.strip()):
            alias_hit = _deep_find_keyed_string(
                arguments,
                ("pattern", "query", "term", "text", "keyword", "needle", "search", "search_term", "regex", "value"),
            )
            if alias_hit:
                pattern = alias_hit
        if not (isinstance(pattern, str) and pattern.strip()):
            pattern = _search_pattern_hint_from_message(user_message) or _search_pattern_hint_from_message(model_text)
        if isinstance(pattern, str) and pattern.strip():
            arguments["pattern"] = pattern.strip()
        if not (isinstance(arguments.get("path"), str) and str(arguments.get("path")).strip()):
            arguments["path"] = "."
        if not (isinstance(arguments.get("pattern"), str) and str(arguments.get("pattern")).strip()):
            return None, {
                "tool_name": tool_name,
                "status": "blocked",
                "error": "invalid_tool_arguments",
                "detail": "Unable to infer fs_search.pattern from model output or user request.",
            }
        # Bound search payload shape to avoid oversized result payload terminalization errors.
        try:
            max_files = int(arguments.get("max_files", 250))
        except Exception:
            max_files = 250
        try:
            max_matches = int(arguments.get("max_matches", 120))
        except Exception:
            max_matches = 120
        arguments["max_files"] = max(1, min(max_files, 500))
        arguments["max_matches"] = max(1, min(max_matches, 200))

    if tool_name == "fs_apply_patch":
        if not (isinstance(arguments.get("path"), str) and str(arguments.get("path")).strip()):
            path_hit = _deep_find_keyed_string(
                arguments,
                ("path", "file_path", "filepath", "target_path", "filename", "name"),
            )
            if path_hit:
                arguments["path"] = path_hit
            elif isinstance(arguments.get("file"), str) and str(arguments.get("file")).strip():
                arguments["path"] = str(arguments.get("file")).strip()
        # Preserve raw patch text exactly; trimming can alter final newline semantics.
        patch_text = _coerce_nonempty_text_preserve(arguments.get("patch"))
        if patch_text is None:
            patch_text = _deep_find_keyed_string(
                arguments,
                ("patch", "diff", "patch_text", "unified_diff", "changes", "edit", "edits", "text", "value"),
            )
        if patch_text is None:
            patch_text = _synthesize_patch_from_arguments(workspace_root, arguments)
        if patch_text is not None:
            arguments["patch"] = patch_text
        if not (isinstance(arguments.get("patch"), str) and str(arguments.get("patch")).strip()):
            return None, {
                "tool_name": tool_name,
                "status": "blocked",
                "error": "invalid_tool_arguments",
                "detail": "Unable to infer fs_apply_patch.patch from model output.",
            }

    if tool_name == "shell_run":
        command_text = _coerce_nonempty_text(arguments.get("command"))
        if command_text is None:
            command_text = _deep_find_keyed_string(
                arguments,
                ("command", "cmd", "shell_command", "script", "command_text", "text", "value"),
            )
        if command_text is None:
            command_text = _shell_command_hint_from_message(user_message) or _shell_command_hint_from_message(model_text)
        if command_text is not None:
            rewritten, rewrite_reason = _rewrite_shell_command_for_env(command_text)
            arguments["command"] = rewritten
            if rewrite_reason:
                emit_metric("tool_shell_rewrite_total", {"reason": rewrite_reason})
        if not (isinstance(arguments.get("command"), str) and str(arguments.get("command")).strip()):
            return None, {
                "tool_name": tool_name,
                "status": "blocked",
                "error": "invalid_tool_arguments",
                "detail": "Unable to infer shell_run.command from model output or user request.",
            }

    shell_mode = str(tool_req.get("shell_mode") or "read_only")
    timeout_sec = int(tool_req.get("timeout_sec", 30))
    prepared = {
        "type": "tool_call",
        "tool_name": tool_name,
        "arguments": arguments,
        "shell_mode": shell_mode,
        "timeout_sec": timeout_sec,
    }
    if write_meta is not None:
        prepared["_write_meta"] = write_meta
    return prepared, None


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version=__version__)
def cli():
    """OpenVegas -- Terminal Arcade for Developers"""
    pass


# ---------------------------------------------------------------------------
# Auth commands
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--otp", is_flag=True, help="Use magic link (OTP) login")
def login(otp: bool):
    """Log in to OpenVegas."""
    from openvegas.auth import SupabaseAuth, AuthError

    try:
        auth = SupabaseAuth()
    except AuthError as e:
        console.print(f"[red]{e}[/red]")
        return

    email = Prompt.ask("Email")

    if otp:
        auth.login_with_otp(email)
        console.print("[green]Magic link sent! Check your email.[/green]")
    else:
        password = Prompt.ask("Password", password=True)
        try:
            result = auth.login_with_email(email, password)
            console.print(
                f"[green]Logged in as {result['email']}[/green]\n"
                f"[dim]user_id: {result.get('user_id', '')}[/dim]"
            )
        except Exception as e:
            console.print(f"[red]Login failed: {e}[/red]")


@cli.command()
def signup():
    """Create a new OpenVegas account."""
    from openvegas.auth import SupabaseAuth, AuthError

    try:
        auth = SupabaseAuth()
    except AuthError as e:
        console.print(f"[red]{e}[/red]")
        return

    email = Prompt.ask("Email")
    password = Prompt.ask("Password", password=True)

    try:
        result = auth.signup(email, password)
        console.print(
            f"[green]Account created for {result['email']}[/green]\n"
            f"[dim]user_id: {result.get('user_id', '')}[/dim]"
        )
    except Exception as e:
        console.print(f"[red]Signup failed: {e}[/red]")


@cli.command()
def logout():
    """Log out of OpenVegas."""
    from openvegas.auth import SupabaseAuth
    try:
        auth = SupabaseAuth()
        auth.logout()
    except Exception:
        from openvegas.config import clear_session
        clear_session()
    console.print("Logged out.")


@cli.command()
def status():
    """Show balance, tier, and stats."""
    async def _status():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            data = await client.get_balance()
            console.print(Panel(
                f"[bold]Balance:[/bold] {data.get('balance', '0.00')} $V\n"
                f"[bold]Tier:[/bold] {data.get('tier', 'free')}\n"
                f"[bold]Lifetime minted:[/bold] {data.get('lifetime_minted', '0.00')} $V\n"
                f"[bold]Lifetime won:[/bold] {data.get('lifetime_won', '0.00')} $V",
                title="OpenVegas Status",
                border_style="cyan",
            ))
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    run_async(_status())


# ---------------------------------------------------------------------------
# Wallet commands
# ---------------------------------------------------------------------------

@cli.command()
def balance():
    """Show your $V balance."""
    async def _balance():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            data = await client.get_balance()
            console.print(f"[bold]{data.get('balance', '0.00')} $V[/bold]")
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_balance())


@cli.command()
def history():
    """Show transaction history."""
    async def _history():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            data = await client.get_history()
            entries = data.get("entries", [])
            if not entries:
                console.print("[dim]No transactions yet.[/dim]")
                return

            table = Table(title="Transaction History")
            table.add_column("Time", style="dim")
            table.add_column("Type")
            table.add_column("Amount", justify="right")
            table.add_column("Reference")

            for entry in entries[:20]:
                table.add_row(
                    entry.get("created_at", "")[:19],
                    entry.get("entry_type", ""),
                    entry.get("amount", ""),
                    entry.get("reference_id", "")[:20],
                )
            console.print(table)
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_history())


@cli.command()
@click.argument("amount")
def deposit(amount: str):
    """Buy $V with cash (returns Stripe checkout URL)."""
    async def _deposit():
        from openvegas.client import OpenVegasClient, APIError
        try:
            amt = Decimal(amount)
        except Exception:
            console.print("[red]Invalid amount. Example: openvegas deposit 10[/red]")
            return

        try:
            client = OpenVegasClient()
            data = await client.create_topup_checkout(amt)
            console.print(f"[green]Top-up ID:[/green] {data.get('topup_id')}")
            console.print(f"[green]Status:[/green] {data.get('status')}")
            if data.get("checkout_url"):
                console.print(f"[bold cyan]Checkout URL:[/bold cyan] {data['checkout_url']}")
            else:
                console.print("[yellow]No checkout URL returned. Try again or check deposit status.[/yellow]")
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_deposit())


@cli.command("deposit-status")
@click.argument("topup_id")
def deposit_status(topup_id: str):
    """Check status of a Stripe top-up."""
    async def _status():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            data = await client.get_topup_status(topup_id)
            console.print(
                f"[bold]Status:[/bold] {data.get('status')} | "
                f"[bold]Credit:[/bold] {data.get('v_credit', '0')} $V"
            )
            if data.get("checkout_url"):
                console.print(f"[dim]Checkout URL: {data['checkout_url']}[/dim]")
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_status())


# ---------------------------------------------------------------------------
# Mint commands
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--amount", type=float, required=True, help="USD amount to burn")
@click.option(
    "--provider", type=click.Choice(["anthropic", "openai", "gemini"]), required=True
)
@click.option(
    "--mode", type=click.Choice(["solo", "split", "sponsor"]), default="solo"
)
def mint(amount: float, provider: str, mode: str):
    """Mint $V by burning LLM tokens (BYOK)."""
    from openvegas.config import get_provider_key

    api_key = get_provider_key(provider)
    if not api_key:
        console.print(
            f"[red]No API key for {provider}. Run: openvegas keys set {provider}[/red]"
        )
        return

    rates_display = {"solo": "standard rate", "split": "+8% $V bonus", "sponsor": "+15% $V bonus"}

    async def _mint():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()

            # 1. Get challenge
            challenge = await client.create_mint_challenge(amount, provider, mode)

            # 2. Show disclosure
            console.print(Panel(
                f"[bold]Mint Mode:[/bold] {mode.title()} Mint ({rates_display[mode]})\n"
                f"[bold]Provider:[/bold] {provider} ({challenge.get('model', '')})\n"
                f"[bold]Target burn ceiling:[/bold] up to ~${amount:.2f} on your account\n"
                f"[bold]Max $V credit cap:[/bold] {challenge.get('max_credit_v', '')} $V\n"
                f"[bold]Note:[/bold] actual burn depends on generated token usage and may be lower.\n"
                f"[bold]Your task:[/bold] {challenge.get('task_prompt', '')[:80]}...",
                title="OpenVegas Mint",
                border_style="green",
            ))

            if not Confirm.ask("Proceed with mint?"):
                console.print("[yellow]Mint cancelled.[/yellow]")
                return

            # 3. Send to backend for proxied mint
            console.print(
                "[dim]Sending key to server for proxied mint "
                "(key used once, never stored)...[/dim]"
            )

            result = await client.verify_mint(
                challenge["id"], challenge["nonce"],
                provider, challenge["model"], api_key,
            )

            console.print(
                f"[bold green]Minted {result['v_credited']} $V[/bold green] "
                f"(actual burn ~${float(result['cost_usd']):.4f} on {provider})"
            )

        except APIError as e:
            console.print(f"[red]Mint failed: {e.detail}[/red]")

    run_async(_mint())


# ---------------------------------------------------------------------------
# Keys management
# ---------------------------------------------------------------------------

@cli.group()
def keys():
    """Manage provider API keys."""
    pass


@keys.command("set")
@click.argument("provider", type=click.Choice(["anthropic", "openai", "gemini"]))
def keys_set(provider: str):
    """Set API key for a provider (stored locally)."""
    from openvegas.config import set_provider_key
    api_key = Prompt.ask(f"Enter {provider} API key", password=True)
    set_provider_key(provider, api_key)
    console.print(f"[green]{provider} API key saved to ~/.openvegas/config.json[/green]")


@keys.command("list")
def keys_list():
    """Show which providers have keys configured."""
    from openvegas.config import load_config
    config = load_config()
    providers = config.get("providers", {})
    for p in ["openai", "anthropic", "gemini"]:
        has_key = bool(providers.get(p, {}).get("api_key"))
        status = "[green]configured[/green]" if has_key else "[dim]not set[/dim]"
        console.print(f"  {p}: {status}")


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("game", type=click.Choice(["horse", "skillshot"]))
@click.option("--stake", type=float, required=True, help="Budget cap for horse ($V) or stake for other games")
@click.option("--horse", type=int, default=None, help="Horse number (horse racing only)")
@click.option(
    "--type", "bet_type",
    type=click.Choice(["win", "place", "show"]), default="win",
)
@click.option("--render/--no-render", default=True, help="Render terminal animation/reveal when available")
@click.option(
    "--demo-force-win/--no-demo-force-win",
    default=False,
    help="Use admin-only demo win endpoint (non-canonical).",
)
def play(
    game: str,
    stake: float,
    horse: int,
    bet_type: str,
    render: bool,
    demo_force_win: bool,
):
    """Play a game and wager $V."""
    async def _play():
        import json
        import uuid
        from openvegas.client import OpenVegasClient, APIError
        from openvegas.games.base import GameResult
        from openvegas.games.horse_racing import HorseRacing
        from openvegas.games.skill_shot import SkillShotGame

        try:
            client = OpenVegasClient()

            if game == "horse":
                if stake <= 0:
                    console.print("[red]Stake must be greater than 0.[/red]")
                    return

                quote = await client.create_horse_quote(
                    bet_type=bet_type,
                    budget_v=Decimal(str(stake)),
                    idempotency_key=f"cli-horse-quote-{uuid.uuid4()}",
                )
                rows = list(quote.get("horses", []) or [])
                if not rows:
                    console.print("[red]No horses returned for quote.[/red]")
                    return

                table = Table(title=f"Horse Board ({bet_type})")
                table.add_column("#", justify="right")
                table.add_column("Horse")
                table.add_column("Odds", justify="right")
                table.add_column("Eff Mult", justify="right")
                table.add_column("Unit Price", justify="right")
                table.add_column("Max Units", justify="right")
                table.add_column("Debit", justify="right")
                table.add_column("Payout If Hit", justify="right")
                table.add_column("Selectable", justify="right")
                selectable_choices: list[str] = []
                for row in rows:
                    selectable = bool(row.get("selectable", False))
                    if selectable:
                        selectable_choices.append(str(row.get("number")))
                    table.add_row(
                        str(row.get("number", "")),
                        str(row.get("name", "")),
                        str(row.get("odds", "")),
                        str(row.get("effective_multiplier", "")),
                        str(row.get("unit_price_v", "")),
                        str(row.get("max_units", "")),
                        str(row.get("debit_v", "")),
                        str(row.get("payout_if_hit_v", "")),
                        "[green]yes[/green]" if selectable else "[red]no[/red]",
                    )
                console.print(table)

                if not selectable_choices:
                    console.print("[red]Budget too low for any horse position.[/red]")
                    return

                horse_choice = horse
                if horse_choice is None:
                    horse_choice = int(
                        Prompt.ask(
                            "Choose horse number",
                            choices=selectable_choices,
                            default=selectable_choices[0],
                        )
                    )
                selected = next((r for r in rows if int(r.get("number", -1)) == int(horse_choice)), None)
                if selected is None:
                    console.print("[red]Selected horse not in quote board.[/red]")
                    return
                if not bool(selected.get("selectable", False)):
                    console.print("[red]Selected horse is not selectable for this budget.[/red]")
                    return

                console.print(Panel(
                    f"[bold]Quote ID:[/bold] {quote.get('quote_id')}\n"
                    f"[bold]Budget:[/bold] {stake:.6f} $V\n"
                    f"[bold]Horse:[/bold] #{selected.get('number')} {selected.get('name')}\n"
                    f"[bold]Odds:[/bold] {selected.get('odds')}\n"
                    f"[bold]Debit:[/bold] {selected.get('debit_v')} $V\n"
                    f"[bold]Payout If Hit:[/bold] {selected.get('payout_if_hit_v')} $V\n"
                    f"[bold]Expires:[/bold] {quote.get('expires_at')}",
                    title="Horse Quote Review",
                    border_style="cyan",
                ))

                if not Confirm.ask("Proceed with quoted horse play?", default=True):
                    console.print("[yellow]Cancelled.[/yellow]")
                    return

                result = await client.play_horse_quote(
                    quote_id=str(quote.get("quote_id", "")),
                    horse=int(horse_choice),
                    idempotency_key=f"cli-horse-play-{uuid.uuid4()}",
                    demo_mode=demo_force_win,
                )
            else:
                bet = {"amount": stake, "type": bet_type}
                result = await client.play_game_demo(game, bet) if demo_force_win else await client.play_game(game, bet)

            net = Decimal(str(result.get("net", "0")))
            payout = Decimal(str(result.get("payout", "0")))
            bet_amount = Decimal(str(result.get("bet_amount", stake)))
            game_id = str(result.get("game_id", ""))

            if render:
                renderer_cls = {
                    "horse": HorseRacing,
                    "skillshot": SkillShotGame,
                }.get(game)
                if renderer_cls:
                    gr = GameResult(
                        game_id=game_id,
                        player_id="",
                        bet_amount=bet_amount,
                        payout=payout,
                        net=net,
                        outcome_data=result.get("outcome_data", {}) or {},
                        server_seed="",
                        server_seed_hash=str(result.get("server_seed_hash", "")),
                        client_seed="",
                        nonce=0,
                        provably_fair=bool(result.get("provably_fair", True)),
                    )
                    await renderer_cls().render(gr, console)

            result_lines: list[str] = []
            if net > 0:
                result_lines.append(f"[bold green]Won {payout} $V! (+{net} net)[/bold green]")
            else:
                result_lines.append(f"[red]Lost {bet_amount} $V.[/red]")

            if result.get("demo_mode"):
                result_lines.append("[bold yellow]DEMO MODE RESULT[/bold yellow] [dim](canonical: false)[/dim]")

            if result.get("demo_mode"):
                result_lines.append(f"[dim]Verify (demo): {verify_hint_for_result(game_id, True)}[/dim]")
            elif result.get("provably_fair"):
                result_lines.append(f"[dim]Verify: {verify_hint_for_result(game_id, False)}[/dim]")

            render_result_panel(
                console,
                "\n".join(result_lines),
                is_win=net > 0,
                animation_enabled=bool(load_config().get("animation", True)),
                title="Result",
            )

        except APIError as e:
            detail = str(e.detail)
            try:
                parsed = json.loads(detail)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict) and parsed.get("error"):
                console.print(f"[red]{parsed.get('error')}: {parsed.get('detail', detail)}[/red]")
            else:
                console.print(f"[red]{e.detail}[/red]")

    run_async(_play())


# ---------------------------------------------------------------------------
# AI Inference
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("prompt")
@click.option("--provider", default=None, help="Provider (openai/anthropic/gemini)")
@click.option("--model", default=None, help="Model ID")
def ask(prompt: str, provider: str | None, model: str | None):
    """Use $V for AI inference."""
    from openvegas.config import get_default_provider, get_default_model

    if provider is None:
        provider = get_default_provider()
    if model is None:
        model = get_default_model(provider)

    async def _ask():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            result = await client.ask(prompt, provider, model)
            console.print(result.get("text", ""))
            console.print(
                f"\n[dim]Cost: {result.get('v_cost', '?')} $V | "
                f"Model: {provider}/{model}[/dim]"
            )
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_ask())


@cli.command()
@click.option("--provider", default=None, help="Provider (openai/anthropic/gemini)")
@click.option("--model", default=None, help="Model ID")
def chat(provider: str | None, model: str | None):
    """OpenVegas conversational shell with slash commands and /ui handoff."""
    from openvegas.config import get_default_provider, get_default_model

    current_provider = provider or get_default_provider()
    current_model = model or get_default_model(current_provider)
    current_thread_id: str | None = None
    current_run_id: str | None = None
    current_run_version: int = 0
    current_signature: str = "sha256:"
    runtime_session_id: str = str(uuid.uuid4())
    workspace_root = str(Path.cwd().resolve())
    workspace_git_root = workspace_root
    workspace_fp = workspace_fingerprint(workspace_root, workspace_git_root)
    plan_mode = False
    approval_mode = "ask"
    conversation_mode = "persistent"
    last_successful_tool: str | None = None
    cfg = load_config()
    verbose_tool_events = normalize_tool_event_density(str(cfg.get("tool_event_density", "compact"))) == "verbose"
    _ = cfg.get("chat_style", "codex")  # retained for backward compatibility only
    _ = cfg.get("approval_ui", "menu")  # retained for backward compatibility only
    session_approval = SessionApprovalState()

    def _show_help() -> None:
        console.print("Chat Commands:")
        console.print("/help - show commands")
        console.print("/provider <openai|anthropic|gemini> [model] - switch provider")
        console.print("/model <model_id> - switch model")
        console.print("/plan [on|off] - toggle plan mode (read-only intent)")
        console.print("/approve <ask|allow|exclude> - mutating tool approval mode")
        console.print("/style - deprecated (minimal style is always on)")
        console.print("/verbose-tools <on|off> - detailed tool event output")
        console.print("/approvals - show session approval overrides")
        console.print("/status - show current chat context")
        console.print("/tooling - show local tool runtime status")
        console.print("/ui - jump into game UI (blocked on pending orchestration state)")
        console.print("/exit - exit chat")

    def _update_fence(payload: dict | None) -> None:
        nonlocal current_run_version, current_signature
        if not isinstance(payload, dict):
            return
        if payload.get("run_version") is not None:
            try:
                current_run_version = int(payload["run_version"])
            except Exception:
                pass
        if payload.get("valid_actions_signature"):
            current_signature = str(payload["valid_actions_signature"])

    def _tool_protocol_prompt(
        user_message: str,
        tool_observations: list[dict],
        ide_context_json: str | None,
    ) -> str:
        obs_json = json.dumps(tool_observations, ensure_ascii=False)
        ide_line = f"IDE context (JSON, capped): {ide_context_json}\n\n" if ide_context_json else ""
        return (
            "You are OpenVegas coding runtime.\n"
            f"Workspace root: {workspace_root}\n"
            f"Plan mode: {'on' if plan_mode else 'off'}\n"
            f"Approval mode: {approval_mode}\n"
            "Available tools:\n"
            "  - Read({ filepath })\n"
            "  - Search({ pattern, path? })\n"
            "  - Write({ filepath, content })\n"
            "  - Bash({ command })\n"
            "  - List({ path? })\n"
            "Rules:\n"
            "1) If a tool is needed, emit a tool call via tool-calling (preferred).\n"
            "   Fallback only if tool-calling is unavailable: output ONE JSON tool_call object.\n"
            "2) If no tool is needed, return the final user-facing answer as normal text.\n"
            "3) Do not claim you cannot access files; tools are available through this runtime.\n"
            "4) Use mutating tools only when required.\n"
            "5) Never repeat the exact same tool call (same tool + same args) after it succeeded; use prior observations to answer.\n\n"
            "6) For requests like 'apply a tiny patch to a temp file', do not ask for clarification.\n"
            "   Choose a safe workspace-local temp file path and produce a minimal valid unified diff.\n\n"
            f"Prior tool observations (JSON): {obs_json}\n\n"
            f"{ide_line}"
            f"User request: {user_message}"
        )

    async def _run_tool_loop(client, user_message: str) -> bool:
        """Return True when assistant produced a final non-tool answer."""
        nonlocal current_thread_id
        nonlocal current_run_version, current_signature
        nonlocal last_successful_tool

        from openvegas.client import APIError

        async def _force_finalize(observations: list[dict[str, Any]], *, reason: str = "completed") -> bool:
            nonlocal current_thread_id
            emit_metric("tool_loop_finalize_reason", {"reason": str(reason or "completed")})
            compression_hint = ""
            if streamed_tools_seen.get("shell_run"):
                compression_hint = (
                    "If shell output was already streamed live, do not replay full output; summarize key results only.\n\n"
                )
            final_prompt = (
                "Use the prior tool observations and answer the user now. "
                "Do not call tools. Return a concise final answer.\n\n"
                f"{compression_hint}"
                f"User request: {user_message}\n"
                f"Observations: {json.dumps(observations, ensure_ascii=False)}"
            )
            final_res = await client.ask(
                final_prompt,
                current_provider,
                current_model,
                idempotency_key=f"chat-finalize-{uuid.uuid4()}",
                thread_id=current_thread_id,
                conversation_mode=conversation_mode,
                persist_context=(conversation_mode == "persistent"),
                enable_tools=False,
            )
            next_thread = final_res.get("thread_id")
            if next_thread:
                current_thread_id = str(next_thread)
            final_text = str(final_res.get("text", "")).strip()
            if final_text:
                render_assistant(console, final_text)
                render_status_bar(
                    console,
                    f"{current_provider}/{current_model}",
                    f"cost {final_res.get('v_cost', '?')} $V",
                    workspace_root,
                )
                return True
            return False

        async def _execute_with_heartbeat(
            *,
            tool_request: dict[str, Any],
            tool_call_id: str,
            execution_token: str,
        ) -> tuple[Any | None, str | None]:
            tool_name_local = str(tool_request.get("tool_name", ""))
            args_local = tool_request.get("arguments", {})
            shell_mode_local = str(tool_request.get("shell_mode") or "read_only")
            timeout_local = int(tool_request.get("timeout_sec") or 30)

            if tool_name_local == "shell_run":
                task = asyncio.create_task(
                    execute_shell_run_streaming(
                        workspace_root=workspace_root,
                        arguments=args_local,
                        timeout_sec=timeout_local,
                        on_stdout=lambda s: console.print(s.rstrip("\n")) if s.strip() else None,
                        on_stderr=lambda s: console.print(f"[red]{s.rstrip()}[/red]") if s.strip() else None,
                    )
                )
            else:
                task = asyncio.create_task(
                    asyncio.to_thread(
                        execute_tool_request,
                        workspace_root=workspace_root,
                        tool_name=tool_name_local,
                        arguments=args_local,
                        shell_mode=shell_mode_local,
                        timeout_sec=timeout_local,
                    )
                )

            heartbeat_interval = 2.0
            heartbeat_failures = 0
            while True:
                try:
                    return await asyncio.wait_for(asyncio.shield(task), timeout=heartbeat_interval), None
                except asyncio.TimeoutError:
                    try:
                        hb = await client.agent_tool_heartbeat(
                            run_id=current_run_id,
                            runtime_session_id=runtime_session_id,
                            tool_call_id=tool_call_id,
                            execution_token=execution_token,
                        )
                        if not bool(hb.get("active", False)):
                            remote_status = str(hb.get("status") or "unknown")
                            if not task.done():
                                task.cancel()
                                try:
                                    await task
                                except Exception:
                                    pass
                            return None, remote_status
                    except APIError as e:
                        heartbeat_failures += 1
                        if heartbeat_failures <= 1:
                            body = e.data if isinstance(e.data, dict) else {}
                            code = body.get("error", "tool_heartbeat_failed")
                            detail = body.get("detail", e.detail)
                            console.print(f"[yellow]{code}: {detail}[/yellow]")
                    except Exception:
                        heartbeat_failures += 1

        tool_observations: list[dict[str, Any]] = []
        executed_tool_calls: dict[str, int] = {}
        streamed_tools_seen: dict[str, bool] = {}
        completion_criteria = _build_completion_criteria(user_message)
        pending_retry_tool_req: dict[str, Any] | None = None
        bridge_caps: dict[str, bool] = {"connected": False, "show_diff": False}
        active_mutation_timeout_hit = False
        active_mutation_observation_changed = False
        progress_fingerprint_prev: str | None = None
        unchanged_progress_iters = 0
        repeated_patch_failures: dict[str, int] = {}
        stall_limit_iters = max(2, int(os.getenv("OPENVEGAS_WORKFLOW_STALL_LIMIT_ITERS", "4")))
        max_active_mutation_wait_sec = max(1.0, float(os.getenv("OPENVEGAS_ACTIVE_MUTATION_TIMEOUT_SEC", "10")))
        patch_failure_repeat_limit = max(2, int(os.getenv("OPENVEGAS_PATCH_FAILURE_REPEAT_LIMIT", "2")))

        def _run_has_started_tool(snapshot: dict[str, Any]) -> bool:
            if str(snapshot.get("current_state") or "") != "running":
                return False
            valid_actions = snapshot.get("valid_actions")
            if not isinstance(valid_actions, list):
                return False
            names = {str(a.get("action", "")).strip().lower() for a in valid_actions if isinstance(a, dict)}
            return "handoff" not in names

        async def _wait_for_unlock_and_refresh() -> bool:
            nonlocal active_mutation_observation_changed
            if not current_run_id:
                return False
            started = time.monotonic()
            delays = (0.25, 0.5, 1.0)
            attempt = 0
            prev_sig: str | None = None
            while (time.monotonic() - started) < max_active_mutation_wait_sec:
                try:
                    snap = await client.agent_run_get(current_run_id)
                except Exception:
                    await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                    attempt += 1
                    continue
                _update_fence(snap if isinstance(snap, dict) else None)
                if isinstance(snap, dict):
                    sig = str(snap.get("valid_actions_signature") or "")
                    if prev_sig is not None and sig and sig != prev_sig:
                        active_mutation_observation_changed = True
                    if sig:
                        prev_sig = sig
                    if not _run_has_started_tool(snap):
                        return True
                await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                attempt += 1
            return False

        def _completion_eval() -> CompletionEvaluation:
            return _evaluate_completion_criteria(completion_criteria, workspace_root)

        def _progress_fingerprint(eval_result: CompletionEvaluation) -> str:
            latest = tool_observations[-1] if tool_observations else {}
            payload = {
                "tool_name": str(latest.get("tool_name", "")),
                "status": str(latest.get("status", latest.get("result_status", ""))),
                "error": str(latest.get("error", "")),
                "result_status": str(latest.get("result_status", "")),
                "artifact_fingerprint": eval_result.fingerprint,
            }
            return _sha256_hex(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))

        async def _continue_or_finalize_for_completion(
            *,
            reason_if_finalize: str,
            step: int,
        ) -> bool:
            nonlocal progress_fingerprint_prev, unchanged_progress_iters
            if not completion_criteria.active:
                return await _force_finalize(tool_observations, reason=reason_if_finalize)
            eval_result = _completion_eval()
            if eval_result.satisfied:
                return await _force_finalize(tool_observations, reason=reason_if_finalize)
            fp = _progress_fingerprint(eval_result)
            if progress_fingerprint_prev is not None and fp == progress_fingerprint_prev:
                unchanged_progress_iters += 1
            else:
                unchanged_progress_iters = 0
            progress_fingerprint_prev = fp
            tool_observations.append(
                {
                    "status": "blocked",
                    "error": "completion_criteria_unmet",
                    "detail": ", ".join(eval_result.missing[:6]),
                }
            )
            if unchanged_progress_iters >= stall_limit_iters:
                return await _force_finalize(tool_observations, reason="workflow_stalled_no_new_observations")
            if step >= (max_tool_steps - 1):
                return await _force_finalize(tool_observations, reason="completion_criteria_unmet_after_retries")
            return False

        async def _call_with_stale_retry(factory, *, endpoint: str):
            nonlocal active_mutation_timeout_hit
            last_exc: APIError | None = None
            max_attempts = 4
            for attempt in range(max_attempts):
                try:
                    return await factory()
                except APIError as e:
                    last_exc = e
                    body = e.data if isinstance(e.data, dict) else {}
                    _update_fence(body)
                    code = str(body.get("error") or "")
                    if code in RETRYABLE_MUTATION_ERRORS and attempt < (max_attempts - 1):
                        emit_metric("tool_cas_conflict_total", {"endpoint": endpoint, "error": code})
                        if code == "active_mutation_in_progress":
                            unlocked = await _wait_for_unlock_and_refresh()
                            if not unlocked:
                                active_mutation_timeout_hit = True
                                raise
                        backoff = _mutation_retry_backoff_sec(code, attempt)
                        if backoff > 0:
                            await asyncio.sleep(backoff)
                        _tool_debug(f"retrying mutation after {code} (attempt {attempt + 1}/{max_attempts})")
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("Unexpected mutation retry state.")

        max_tool_steps = max(4, min(40, int(os.getenv("OPENVEGAS_CHAT_MAX_TOOL_STEPS", "24"))))
        for step in range(max_tool_steps):
            cleaned_text = ""
            model_text = ""
            injected_temp_patch = False
            candidate_tool_calls: list[dict[str, Any]] = []
            if pending_retry_tool_req is not None:
                candidate_tool_calls = [pending_retry_tool_req]
                pending_retry_tool_req = None
            force_patch_intent = bool(
                last_successful_tool == "fs_apply_patch" and _is_patch_repeat_followup_intent(user_message)
            )
            if force_patch_intent:
                _tool_debug(f"forcing patch follow-up intent from prior tool={last_successful_tool!r}")

            if (
                step == 0
                and not candidate_tool_calls
                and not tool_observations
                and (force_patch_intent or _is_patch_smoke_intent(user_message))
            ):
                synthetic = _synth_patch_tool_req_for_intent(
                    user_message=user_message,
                    tool_observations=tool_observations,
                    force_patch_intent=force_patch_intent,
                )
                if synthetic is not None:
                    candidate_tool_calls.append(synthetic)
                    injected_temp_patch = True
                    _tool_debug("injected synthetic fs_apply_patch on step 0")

            if not candidate_tool_calls:
                ide_context_json: str | None = None
                if current_run_id:
                    try:
                        ide_context = await asyncio.wait_for(
                            client.ide_get_context(
                                run_id=current_run_id,
                                runtime_session_id=runtime_session_id,
                            ),
                            timeout=3.0,
                        )
                        if isinstance(ide_context, dict):
                            ide_context_json = json.dumps(ide_context, ensure_ascii=False)[:8192]
                            bridge_caps["connected"] = True
                            bridge_caps["show_diff"] = True
                    except Exception:
                        ide_context_json = None

                prompt = _tool_protocol_prompt(user_message, tool_observations, ide_context_json)
                ask_idem = f"chat-ask-{uuid.uuid4()}"
                result = await client.ask(
                    prompt,
                    current_provider,
                    current_model,
                    idempotency_key=ask_idem,
                    thread_id=current_thread_id,
                    conversation_mode=conversation_mode,
                    persist_context=(conversation_mode == "persistent"),
                    enable_tools=True,
                )
                next_thread = result.get("thread_id")
                if next_thread:
                    current_thread_id = str(next_thread)
                model_text = str(result.get("text", "")).strip()
                cleaned_text = model_text
                candidate_tool_calls = _collect_tool_call_candidates(result.get("tool_calls"), model_text)
                if cleaned_text:
                    render_assistant(console, cleaned_text)
                    render_status_bar(
                        console,
                        f"{current_provider}/{current_model}",
                        f"cost {result.get('v_cost', '?')} $V",
                        workspace_root,
                    )

            if not candidate_tool_calls:
                fallback_req = _synth_patch_tool_req_for_intent(
                    user_message=user_message,
                    tool_observations=tool_observations,
                    force_patch_intent=force_patch_intent,
                )
                if fallback_req is not None:
                    candidate_tool_calls.append(fallback_req)
                    _tool_debug("fallback synthesized fs_apply_patch after model produced no tool request")
                else:
                    if await _continue_or_finalize_for_completion(
                        reason_if_finalize="completed",
                        step=step,
                    ):
                        return True
                    continue

            if not current_run_id:
                console.print("[red]Tool request ignored: no active run.[/red]")
                return bool(cleaned_text)

            preprocessed_calls: list[dict[str, Any]] = []
            for raw_call in candidate_tool_calls:
                prepared, prep_error = _preprocess_tool_request_for_runtime(
                    tool_req=raw_call,
                    user_message=user_message,
                    model_text=model_text,
                    workspace_root=workspace_root,
                    tool_observations=tool_observations,
                    force_patch_intent=force_patch_intent,
                )
                if prep_error is not None:
                    tool_observations.append(prep_error)
                    continue
                if prepared is not None:
                    preprocessed_calls.append(prepared)

            if not preprocessed_calls:
                if any(str(obs.get("status")) == "noop" for obs in tool_observations):
                    if await _continue_or_finalize_for_completion(
                        reason_if_finalize="completed",
                        step=step,
                    ):
                        return True
                    continue
                reason = "blocked_invalid_args"
                if any(str(obs.get("error")) == "unknown_tool_name" for obs in tool_observations):
                    reason = "unknown_tool"
                if await _continue_or_finalize_for_completion(
                    reason_if_finalize=reason,
                    step=step,
                ):
                    return True
                continue

            # Continue-aligned execution discipline: process one tool call at a time,
            # then re-ask model with fresh observations.
            if len(preprocessed_calls) > 1:
                emit_metric(
                    "tool_batch_truncated_total",
                    {"count": str(len(preprocessed_calls))},
                )
                preprocessed_calls = preprocessed_calls[:1]

            did_any_execution = False
            duplicate_suppressed = False
            policy_denied = False
            mutation_conflict = False
            terminal_reason: str | None = None
            for tool_req in preprocessed_calls:
                tool_name = str(tool_req.get("tool_name", "")).strip()
                arguments = tool_req.get("arguments", {})
                shell_mode = tool_req.get("shell_mode")
                timeout_sec = int(tool_req.get("timeout_sec", 30))
                write_meta = tool_req.get("_write_meta") if isinstance(tool_req.get("_write_meta"), dict) else None

                policy = evaluate_tool_policy(
                    tool_name=tool_name,
                    shell_mode=str(shell_mode or "read_only"),
                    approval_mode=approval_mode,
                )
                if policy == ToolPolicyDecision.EXCLUDE:
                    policy_denied = True
                    tool_observations.append(
                        {
                            "tool_name": tool_name,
                            "status": "blocked",
                            "error": "tool_excluded_by_policy",
                        }
                    )
                    continue
                # Existing-file Write path: shape edits via IDE diff or terminal fallback before approval/propose.
                if (
                    tool_name == "fs_apply_patch"
                    and isinstance(write_meta, dict)
                    and bool(write_meta.get("existing_file"))
                    and current_run_id
                ):
                    raw_diff_result: dict[str, Any] | None = None
                    diff_surface = ""
                    write_path = str(write_meta.get("path") or "")
                    patch_text = str(arguments.get("patch") or "")
                    if (
                        bool(bridge_caps.get("connected"))
                        and bool(bridge_caps.get("show_diff"))
                    ):
                        try:
                            raw_diff_result = await client.ide_show_diff(
                                run_id=current_run_id,
                                runtime_session_id=runtime_session_id,
                                path=write_path,
                                new_contents=str(write_meta.get("new_contents") or ""),
                                allow_partial_accept=True,
                            )
                            diff_surface = "ide"
                            emit_metric("tool_show_diff_invoked_total", {"tool": "write"})
                        except APIError as e:
                            body = e.data if isinstance(e.data, dict) else {}
                            code = str(body.get("error") or "")
                            if code in {"invalid_transition"}:
                                bridge_caps["connected"] = False
                                bridge_caps["show_diff"] = False
                                emit_metric("tool_show_diff_skipped_total", {"reason": "bridge_unavailable"})
                            else:
                                detail = body.get("detail", e.detail)
                                console.print(f"[yellow]show_diff skipped: {detail}[/yellow]")

                    if raw_diff_result is None and patch_text.strip() and _terminal_diff_fallback_enabled():
                        parsed_original = parse_unified_patch_terminal(patch_text)
                        if parsed_original.parse_error:
                            tool_observations.append(
                                {
                                    "tool_name": tool_name,
                                    "status": "blocked",
                                    "error": "user_declined_edit",
                                    "detail": "Patch could not be parsed for diff review.",
                                }
                            )
                            continue

                        max_hunks = max(1, int(os.getenv("OPENVEGAS_TERMINAL_DIFF_MAX_HUNKS", "80")))
                        max_patch_bytes = max(
                            1024,
                            int(os.getenv("OPENVEGAS_TERMINAL_DIFF_MAX_PATCH_BYTES", "262144")),
                        )
                        patch_bytes = len(patch_text.encode("utf-8"))
                        if parsed_original.hunks_total > max_hunks or patch_bytes > max_patch_bytes:
                            emit_metric("tool_terminal_diff_invoked_total", {"tool": "write"})
                            emit_metric("tool_terminal_diff_error_total", {"tool": "write", "reason": "large_diff"})
                            emit_metric(
                                "tool_diff_decision_total",
                                {"diff_surface": "terminal", "diff_outcome": "error"},
                            )
                            tool_observations.append(
                                {
                                    "tool_name": tool_name,
                                    "status": "blocked",
                                    "error": "user_declined_edit_large_diff",
                                    "detail": "Patch exceeds terminal diff review bounds.",
                                }
                            )
                            continue

                        emit_metric("tool_terminal_diff_invoked_total", {"tool": "write"})
                        _drain_stdin_buffer(window_ms=0)
                        raw_diff_result = review_patch_terminal(
                            path=write_path,
                            patch_text=patch_text,
                            allow_partial_accept=True,
                            console=console,
                        )
                        _drain_stdin_buffer(window_ms=0)
                        diff_surface = "terminal"
                    elif raw_diff_result is None and patch_text.strip():
                        emit_metric("tool_show_diff_skipped_total", {"reason": "terminal_fallback_disabled"})

                    if raw_diff_result is not None:
                        diff_result = normalize_show_diff_result(raw_diff_result, default_path=write_path)
                        decisions = diff_result.get("decisions", [])
                        hunks_total = int(diff_result.get("hunks_total", len(decisions)))
                        accepted_hunks: set[int] = set()
                        for d in decisions:
                            if not isinstance(d, dict):
                                continue
                            if str(d.get("decision")) != "accepted":
                                continue
                            try:
                                accepted_hunks.add(int(d.get("hunk_index")))
                            except Exception:
                                continue

                        reject_reason = "reject_all"
                        if bool(diff_result.get("timed_out")):
                            reject_reason = "timeout"

                        if hunks_total > 0 and not accepted_hunks:
                            if diff_surface == "ide":
                                emit_metric("tool_show_diff_rejected_total", {"tool": "write"})
                            elif diff_surface == "terminal":
                                emit_metric("tool_terminal_diff_rejected_total", {"tool": "write"})
                            emit_metric(
                                "tool_diff_decision_total",
                                {"diff_surface": diff_surface or "unknown", "diff_outcome": reject_reason},
                            )
                            tool_observations.append(
                                {
                                    "tool_name": tool_name,
                                    "status": "blocked",
                                    "error": "user_declined_edit",
                                    "detail": "All diff hunks were rejected.",
                                }
                            )
                            continue

                        if hunks_total > 0 and len(accepted_hunks) < hunks_total:
                            filtered_patch, filtered_parsed = _filter_patch_by_accepted_hunks_with_parsed(
                                patch_text,
                                accepted_hunks,
                            )
                            if (
                                not filtered_patch
                                or filtered_parsed is None
                                or not _is_valid_filtered_patch(filtered_patch, parsed_patch=filtered_parsed)
                            ):
                                if diff_surface == "ide":
                                    emit_metric("tool_show_diff_rejected_total", {"tool": "write"})
                                elif diff_surface == "terminal":
                                    emit_metric("tool_terminal_diff_error_total", {"tool": "write", "reason": "invalid_filtered_patch"})
                                emit_metric(
                                    "tool_diff_decision_total",
                                    {"diff_surface": diff_surface or "unknown", "diff_outcome": "error"},
                                )
                                tool_observations.append(
                                    {
                                        "tool_name": tool_name,
                                        "status": "blocked",
                                        "error": "user_declined_edit",
                                        "detail": "Filtered patch was invalid after hunk decisions.",
                                    }
                                )
                                continue
                            arguments["patch"] = filtered_patch
                            patch_text = filtered_patch
                            footprint = filtered_patch_footprint(filtered_parsed)
                            write_meta = dict(write_meta)
                            write_meta["filtered_target_files"] = list(footprint.get("target_files", []))
                            write_meta["filtered_hunks_total"] = int(footprint.get("hunks_total", 0))
                            write_meta["filtered_touched_per_file"] = dict(footprint.get("touched_per_file", {}))
                            tool_req["_write_meta"] = write_meta
                            if diff_surface == "ide":
                                emit_metric(
                                    "tool_show_diff_partial_accept_total",
                                    {"tool": "write", "accepted": str(len(accepted_hunks)), "total": str(hunks_total)},
                                )
                            elif diff_surface == "terminal":
                                emit_metric(
                                    "tool_terminal_diff_partial_accept_total",
                                    {"tool": "write", "accepted": str(len(accepted_hunks)), "total": str(hunks_total)},
                                )
                            emit_metric(
                                "tool_diff_decision_total",
                                {"diff_surface": diff_surface or "unknown", "diff_outcome": "partial"},
                            )
                        elif hunks_total > 0:
                            if diff_surface == "ide":
                                emit_metric("tool_show_diff_accept_all_total", {"tool": "write"})
                            elif diff_surface == "terminal":
                                emit_metric("tool_terminal_diff_accept_all_total", {"tool": "write"})
                            emit_metric(
                                "tool_diff_decision_total",
                                {"diff_surface": diff_surface or "unknown", "diff_outcome": "accept_all"},
                            )

                call_key = _semantic_tool_signature(tool_name, arguments, str(shell_mode or "read_only"))
                if executed_tool_calls.get(call_key, 0) >= 1:
                    duplicate_suppressed = True
                    tool_observations.append(
                        {
                            "tool_name": tool_name,
                            "status": "blocked",
                            "error": "duplicate_tool_call",
                            "detail": "Repeated identical tool call suppressed.",
                        }
                    )
                    continue

                if policy == ToolPolicyDecision.ASK:
                    action_scope = action_scope_for(tool_name, arguments if isinstance(arguments, dict) else {})
                    if not should_auto_allow(session_approval, action_scope):
                        action_label = describe_tool_action(tool_name, arguments)
                        _drain_stdin_buffer(window_ms=0)
                        decision = choose_approval(
                            tool_name=tool_name,
                            arguments=arguments if isinstance(arguments, dict) else {},
                            action_label=action_label,
                            console=console,
                        )
                        _drain_stdin_buffer(window_ms=0)
                        apply_approval_decision(session_approval, action_scope, decision)
                        if decision == ApprovalDecision.DENY_AND_REPLAN:
                            policy_denied = True
                            tool_observations.append(
                                {
                                    "tool_name": tool_name,
                                    "status": "blocked",
                                    "error": "approval_denied_replan",
                                }
                            )
                            continue

                try:
                    proposed = await _call_with_stale_retry(
                        lambda: client.agent_tool_propose(
                            run_id=current_run_id,
                            runtime_session_id=runtime_session_id,
                            expected_run_version=current_run_version,
                            expected_valid_actions_signature=current_signature,
                            idempotency_key=f"tool-propose-{uuid.uuid4()}",
                            tool_name=tool_name,
                            arguments=arguments,
                            shell_mode=str(shell_mode) if shell_mode is not None else None,
                            timeout_sec=timeout_sec,
                            plan_mode=plan_mode,
                        ),
                        endpoint="propose",
                    )
                except APIError as e:
                    body = e.data if isinstance(e.data, dict) else {}
                    code = body.get("error", "tool_propose_failed")
                    if code in {"stale_projection", "idempotency_conflict", "active_mutation_in_progress"}:
                        emit_metric("tool_cas_conflict_total", {"endpoint": "propose", "error": code})
                    if code == "active_mutation_in_progress":
                        mutation_conflict = True
                        if not active_mutation_timeout_hit:
                            pending_retry_tool_req = {
                                "type": "tool_call",
                                "tool_name": tool_name,
                                "arguments": dict(arguments) if isinstance(arguments, dict) else {},
                                "shell_mode": str(shell_mode or "read_only"),
                                "timeout_sec": timeout_sec,
                            }
                    detail = body.get("detail", e.detail)
                    console.print(f"[red]{code}: {detail}[/red]")
                    tool_observations.append({"tool_name": tool_name, "status": "proposal_error", "error": code})
                    if mutation_conflict:
                        break
                    continue

                _update_fence(proposed)
                tool_request = proposed.get("tool_request")
                if not isinstance(tool_request, dict):
                    err = proposed.get("error")
                    if err:
                        console.print(f"[yellow]{err}: {proposed.get('detail', '')}[/yellow]")
                        tool_observations.append({"tool_name": tool_name, "status": "blocked", "error": err})
                        continue
                    console.print("[red]Tool proposal did not return a tool_request payload.[/red]")
                    continue

                tool_call_id = str(tool_request.get("tool_call_id", ""))
                execution_token = str(tool_request.get("execution_token", ""))
                if not tool_call_id or not execution_token:
                    console.print("[red]Invalid tool request payload from server.[/red]")
                    tool_observations.append({"tool_name": tool_name, "status": "start_error", "error": "invalid_tool_request_payload"})
                    continue

                try:
                    started = await _call_with_stale_retry(
                        lambda: client.agent_tool_start(
                            run_id=current_run_id,
                            runtime_session_id=runtime_session_id,
                            tool_call_id=tool_call_id,
                            execution_token=execution_token,
                            expected_run_version=current_run_version,
                            expected_valid_actions_signature=current_signature,
                            idempotency_key=f"tool-start-{uuid.uuid4()}",
                        ),
                        endpoint="start",
                    )
                    _update_fence(started)
                except APIError as e:
                    body = e.data if isinstance(e.data, dict) else {}
                    code = body.get("error", "tool_start_failed")
                    if code in {"stale_projection", "idempotency_conflict", "active_mutation_in_progress"}:
                        emit_metric("tool_cas_conflict_total", {"endpoint": "start", "error": code})
                    if code == "active_mutation_in_progress":
                        mutation_conflict = True
                        if not active_mutation_timeout_hit:
                            pending_retry_tool_req = {
                                "type": "tool_call",
                                "tool_name": tool_name,
                                "arguments": dict(arguments) if isinstance(arguments, dict) else {},
                                "shell_mode": str(shell_mode or "read_only"),
                                "timeout_sec": timeout_sec,
                            }
                    detail = body.get("detail", e.detail)
                    console.print(f"[red]{code}: {detail}[/red]")
                    tool_observations.append(
                        {"tool_name": tool_name, "tool_call_id": tool_call_id, "status": "start_error", "error": code}
                    )
                    if mutation_conflict:
                        break
                    continue

                event_label = describe_tool_action(tool_name, arguments)
                event_detail = f"id={tool_call_id}" if verbose_tool_events else ""
                render_tool_event(console, event_label, event_detail)
                outcome, inactive_status = await _execute_with_heartbeat(
                    tool_request=tool_request,
                    tool_call_id=tool_call_id,
                    execution_token=execution_token,
                )
                if tool_name == "shell_run":
                    streamed_tools_seen["shell_run"] = True
                if outcome is None:
                    emit_metric(
                        "tool_heartbeat_miss_total",
                        {"remote_status": str(inactive_status or "inactive")},
                    )
                    tool_observations.append(
                        {
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "status": "inactive",
                            "remote_status": inactive_status,
                        }
                    )
                    continue

                # Continue-style recovery: for Write-derived edits, if patch apply fails due
                # hunk drift, regenerate a fresh patch from current file state and retry once.
                if (
                    str(outcome.result_status) == "failed"
                    and tool_name == "fs_apply_patch"
                    and isinstance(write_meta, dict)
                    and isinstance(write_meta.get("path"), str)
                    and isinstance(write_meta.get("new_contents"), str)
                ):
                    original_outcome = outcome
                    original_patch = str(arguments.get("patch", ""))
                    regen_patch = original_patch
                    regen, regen_err = _prepare_write_patch(
                        workspace_root=workspace_root,
                        arguments={
                            "filepath": str(write_meta.get("path")),
                            "content": str(write_meta.get("new_contents")),
                        },
                    )
                    if regen_err is not None:
                        if str(regen_err.get("status")) == "noop" and str(regen_err.get("error")) == "no_change":
                            emit_metric("tool_apply_patch_retry_total", {"status": "already_applied"})
                            outcome = ToolExecutionResult(
                                result_status="succeeded",
                                result_payload={
                                    "ok": True,
                                    "detail": "Write target already matches requested content.",
                                    "recovery_mode": "already_applied",
                                },
                                stdout=original_outcome.stdout,
                                stderr=original_outcome.stderr,
                            )
                        else:
                            fallback = _attempt_bootstrap_write_fallback(
                                workspace_root=workspace_root,
                                rel_path=str(write_meta.get("path") or ""),
                                new_contents=str(write_meta.get("new_contents") or ""),
                                existing_file=bool(write_meta.get("existing_file")),
                            )
                            if fallback is not None and str(fallback.result_status) == "succeeded":
                                emit_metric("tool_apply_patch_retry_total", {"status": "bootstrap_fallback_succeeded"})
                                outcome = fallback
                            else:
                                emit_metric("tool_apply_patch_retry_total", {"status": "prepare_failed"})
                                reason = (
                                    "patch_recovery_failed_bootstrap_fallback_exhausted"
                                    if fallback is not None
                                    else "patch_recovery_failed"
                                )
                                detail = str(regen_err.get("detail") or "Patch recovery preparation failed.")
                                outcome = ToolExecutionResult(
                                    result_status="failed",
                                    result_payload=_patch_recovery_payload(
                                        reason_code=reason,
                                        detail=detail,
                                        original_outcome=original_outcome,
                                        retry_outcome=fallback,
                                        original_patch=original_patch,
                                        regenerated_patch=regen_patch,
                                    ),
                                    stdout=(fallback.stdout if fallback is not None else original_outcome.stdout),
                                    stderr=(fallback.stderr if fallback is not None else original_outcome.stderr),
                                )
                                terminal_reason = reason
                    elif isinstance(regen, dict):
                        regen_args = dict(regen.get("arguments", {}))
                        regenerated_patch = str(regen_args.get("patch", ""))
                        regen_patch = regenerated_patch
                        scope_failure = _validate_patch_recovery_scope(
                            original_patch=original_patch,
                            regenerated_patch=regenerated_patch,
                        )
                        if scope_failure is not None:
                            emit_metric("tool_apply_patch_retry_total", {"status": "scope_rejected"})
                            outcome = ToolExecutionResult(
                                result_status="failed",
                                result_payload=_patch_recovery_payload(
                                    reason_code=scope_failure,
                                    detail="Regenerated patch exceeded bounded recovery scope.",
                                    original_outcome=original_outcome,
                                    retry_outcome=None,
                                    original_patch=original_patch,
                                    regenerated_patch=regenerated_patch,
                                    scope_guard_rejected=True,
                                    scope_guard_subreason=scope_failure,
                                ),
                                stdout=original_outcome.stdout,
                                stderr=original_outcome.stderr,
                            )
                            terminal_reason = "patch_recovery_scope_expansion"
                        else:
                            retry_outcome = await asyncio.to_thread(
                                execute_tool_request,
                                workspace_root=workspace_root,
                                tool_name="fs_apply_patch",
                                arguments=regen_args,
                                shell_mode=str(shell_mode or "read_only"),
                                timeout_sec=timeout_sec,
                            )
                            if str(retry_outcome.result_status) == "succeeded":
                                emit_metric("tool_apply_patch_retry_total", {"status": "succeeded"})
                                outcome = retry_outcome
                                arguments = regen_args
                            else:
                                fallback = _attempt_bootstrap_write_fallback(
                                    workspace_root=workspace_root,
                                    rel_path=str(write_meta.get("path") or ""),
                                    new_contents=str(write_meta.get("new_contents") or ""),
                                    existing_file=bool(write_meta.get("existing_file")),
                                )
                                if fallback is not None and str(fallback.result_status) == "succeeded":
                                    emit_metric("tool_apply_patch_retry_total", {"status": "bootstrap_fallback_succeeded"})
                                    outcome = fallback
                                else:
                                    emit_metric("tool_apply_patch_retry_total", {"status": "failed"})
                                    reason = (
                                        "patch_recovery_failed_bootstrap_fallback_exhausted"
                                        if fallback is not None
                                        else "patch_recovery_failed"
                                    )
                                    outcome = ToolExecutionResult(
                                        result_status="failed",
                                        result_payload=_patch_recovery_payload(
                                            reason_code=reason,
                                            detail="Patch recovery retry failed.",
                                            original_outcome=original_outcome,
                                            retry_outcome=(fallback if fallback is not None else retry_outcome),
                                            original_patch=original_patch,
                                            regenerated_patch=regenerated_patch,
                                        ),
                                        stdout=(fallback.stdout if fallback is not None else retry_outcome.stdout),
                                        stderr=(fallback.stderr if fallback is not None else retry_outcome.stderr),
                                    )
                                    terminal_reason = reason

                try:
                    stdout_cap = max(1024, int(os.getenv("OPENVEGAS_TOOL_STDOUT_MAX_BYTES", "131072")))
                    stderr_cap = max(1024, int(os.getenv("OPENVEGAS_TOOL_STDERR_MAX_BYTES", "131072")))
                    stdout_meta = redact_hash_truncate(outcome.stdout or "", stdout_cap)
                    stderr_meta = redact_hash_truncate(outcome.stderr or "", stderr_cap)
                    submission_hash = compute_result_submission_hash(
                        result_status=outcome.result_status,
                        result_payload=outcome.result_payload,
                        stdout_sha256=stdout_meta.sha256,
                        stderr_sha256=stderr_meta.sha256,
                    )
                    finished = await _call_with_stale_retry(
                        lambda: client.agent_tool_result(
                            run_id=current_run_id,
                            runtime_session_id=runtime_session_id,
                            tool_call_id=tool_call_id,
                            execution_token=execution_token,
                            result_status=outcome.result_status,
                            result_payload=outcome.result_payload,
                            stdout=outcome.stdout,
                            stderr=outcome.stderr,
                            stdout_truncated=stdout_meta.truncated,
                            stderr_truncated=stderr_meta.truncated,
                            stdout_sha256=stdout_meta.sha256,
                            stderr_sha256=stderr_meta.sha256,
                            result_submission_hash=submission_hash,
                        ),
                        endpoint="result",
                    )
                    _update_fence(finished)
                except APIError as e:
                    body = e.data if isinstance(e.data, dict) else {}
                    _update_fence(body)
                    code = body.get("error", "tool_result_failed")
                    if code in {"stale_projection", "idempotency_conflict", "active_mutation_in_progress"}:
                        emit_metric("tool_cas_conflict_total", {"endpoint": "result", "error": code})
                    if code == "active_mutation_in_progress":
                        mutation_conflict = True
                        if not active_mutation_timeout_hit:
                            pending_retry_tool_req = {
                                "type": "tool_call",
                                "tool_name": tool_name,
                                "arguments": dict(arguments) if isinstance(arguments, dict) else {},
                                "shell_mode": str(shell_mode or "read_only"),
                                "timeout_sec": timeout_sec,
                            }
                    detail = body.get("detail", e.detail)
                    console.print(f"[red]{code}: {detail}[/red]")
                    tool_observations.append(
                        {
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "status": "result_error",
                            "error": code,
                        }
                    )
                    # Best-effort cleanup: if result terminalization failed, attempt cancel
                    # to avoid leaving run blocked by a started tool row.
                    try:
                        await client.agent_tool_cancel(
                            run_id=current_run_id,
                            runtime_session_id=runtime_session_id,
                            tool_call_id=tool_call_id,
                            execution_token=execution_token,
                        )
                    except Exception:
                        pass
                    if mutation_conflict:
                        break
                    continue

                tool_observations.append(
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "result_status": outcome.result_status,
                        "result_payload": outcome.result_payload,
                        "stdout": "" if streamed_tools_seen.get(tool_name) else outcome.stdout[-8000:],
                        "stderr": outcome.stderr[-4000:],
                        "output_streamed": bool(streamed_tools_seen.get(tool_name)),
                    }
                )
                render_tool_result(
                    console,
                    describe_tool_action(tool_name, arguments),
                    str(outcome.result_status),
                )
                render_status_bar(
                    console,
                    f"{current_provider}/{current_model}",
                    f"tool {str(outcome.result_status)}",
                    workspace_root,
                )
                if str(outcome.result_status) == "succeeded":
                    last_successful_tool = tool_name
                    _tool_debug(f"last_successful_tool={last_successful_tool}")
                    if tool_name == "fs_apply_patch":
                        repeated_patch_failures.clear()
                elif tool_name == "fs_apply_patch":
                    failure_sig = _patch_failure_signature(
                        arguments=arguments if isinstance(arguments, dict) else {},
                        write_meta=write_meta if isinstance(write_meta, dict) else None,
                        outcome=outcome,
                    )
                    repeat_count = repeated_patch_failures.get(failure_sig, 0) + 1
                    repeated_patch_failures[failure_sig] = repeat_count
                    emit_metric("tool_apply_patch_same_intent_fail_total", {"count": str(repeat_count)})
                    if repeat_count >= patch_failure_repeat_limit:
                        tool_observations.append(
                            {
                                "tool_name": tool_name,
                                "status": "blocked",
                                "error": "patch_recovery_failed_same_intent_circuit_break",
                                "detail": "Repeated identical patch failure; stopped retry loop.",
                            }
                        )
                        return await _force_finalize(
                            tool_observations,
                            reason="patch_recovery_failed_same_intent_circuit_break",
                        )
                executed_tool_calls[call_key] = executed_tool_calls.get(call_key, 0) + 1
                did_any_execution = True
                if terminal_reason is not None:
                    return await _force_finalize(tool_observations, reason=terminal_reason)

            if injected_temp_patch and did_any_execution:
                if await _continue_or_finalize_for_completion(
                    reason_if_finalize="completed",
                    step=step,
                ):
                    return True
                continue
            if not did_any_execution and preprocessed_calls:
                if mutation_conflict:
                    if active_mutation_timeout_hit:
                        timeout_reason = (
                            "workflow_stalled_no_new_observations"
                            if not active_mutation_observation_changed
                            else "active_mutation_timeout"
                        )
                        return await _force_finalize(tool_observations, reason=timeout_reason)
                    if pending_retry_tool_req is not None:
                        continue
                    return await _force_finalize(tool_observations, reason="active_mutation_in_progress")
                if duplicate_suppressed:
                    if await _continue_or_finalize_for_completion(
                        reason_if_finalize="duplicate_suppressed",
                        step=step,
                    ):
                        return True
                    continue
                if policy_denied:
                    if await _continue_or_finalize_for_completion(
                        reason_if_finalize="policy_denied",
                        step=step,
                    ):
                        return True
                    continue
                if any(str(obs.get("error")) == "unknown_tool_name" for obs in tool_observations):
                    if await _continue_or_finalize_for_completion(
                        reason_if_finalize="unknown_tool",
                        step=step,
                    ):
                        return True
                    continue
                if await _continue_or_finalize_for_completion(
                    reason_if_finalize="blocked_invalid_args",
                    step=step,
                ):
                    return True
                continue
        console.print(f"[yellow]Stopped after max tool iterations ({max_tool_steps}).[/yellow]")
        if completion_criteria.active and not _completion_eval().satisfied:
            return await _force_finalize(tool_observations, reason="completion_criteria_unmet_after_retries")
        return await _force_finalize(tool_observations, reason="max_iterations")

    async def _run_chat() -> str:
        nonlocal current_provider, current_model, current_thread_id
        nonlocal current_run_id, current_run_version, current_signature
        nonlocal plan_mode, conversation_mode, workspace_root, workspace_fp, approval_mode
        nonlocal verbose_tool_events
        from openvegas.client import APIError, OpenVegasClient

        low_floor_usd = Decimal(os.getenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5.00"))
        v_per_usd = Decimal(os.getenv("V_PER_USD", "100"))
        suggest_cooldown_sec = max(30, int(os.getenv("TOPUP_SUGGEST_COOLDOWN_SEC", "300")))
        last_seen_balance_usd: Decimal | None = None
        shown_topup_id: str | None = None
        shown_topup_status: str | None = None
        shown_at_monotonic: float = 0.0

        def _balance_usd_equiv(balance_v_raw: str | Decimal | float | int | None) -> Decimal:
            raw = Decimal(str(balance_v_raw or "0"))
            if v_per_usd <= 0:
                return Decimal("0.00")
            return (raw / v_per_usd).quantize(Decimal("0.01"))

        def _material_balance_change(prev_usd: Decimal | None, next_usd: Decimal) -> bool:
            if prev_usd is None:
                return next_usd <= low_floor_usd
            crossed_floor = (prev_usd > low_floor_usd and next_usd <= low_floor_usd) or (
                prev_usd <= low_floor_usd and next_usd > low_floor_usd
            )
            delta = abs(next_usd - prev_usd)
            return crossed_floor or delta >= Decimal("0.50")

        async def _maybe_render_low_balance_hint(*, force: bool = False) -> None:
            nonlocal last_seen_balance_usd, shown_topup_id, shown_topup_status, shown_at_monotonic
            try:
                bal = await client.get_balance()
                balance_v = bal.get("balance", "0")
                usd_now = _balance_usd_equiv(balance_v)

                wakeup_by_status = False
                if shown_topup_id:
                    try:
                        topup_state = await client.get_topup_status(shown_topup_id)
                        current_status = str(topup_state.get("status", ""))
                        if current_status and current_status != (shown_topup_status or ""):
                            if current_status in {"paid", "expired", "failed", "manual_reconciliation_required"}:
                                wakeup_by_status = True
                                shown_topup_id = None
                                shown_topup_status = None
                    except Exception:
                        pass

                should_check = force or wakeup_by_status or _material_balance_change(last_seen_balance_usd, usd_now)
                last_seen_balance_usd = usd_now
                if not should_check:
                    return

                if shown_topup_id and (time.monotonic() - shown_at_monotonic) < suggest_cooldown_sec:
                    emit_metric("topup_suggest_suppressed_total", {"reason": "cooldown"})
                    return

                hint = await client.suggest_topup()
                if not bool(hint.get("low_balance", False)):
                    return
                render_topup_hint(console, hint)
                emit_metric("topup_qr_generated_total", {"surface": "cli"})
                shown_topup_id = str(hint.get("topup_id") or "") or None
                shown_topup_status = str(hint.get("status") or "") or None
                shown_at_monotonic = time.monotonic()
            except Exception:
                return

        def _read_chat_message() -> str:
            first = Prompt.ask("chat")
            extras = _drain_stdin_buffer(window_ms=40)
            if not extras:
                return first.strip()
            return "\n".join([first, *extras]).strip()

        client = OpenVegasClient()
        try:
            mode = await client.get_mode()
            conversation_mode = str(mode.get("conversation_mode", "persistent"))
        except Exception:
            conversation_mode = "persistent"

        try:
            run_info = await client.agent_run_create(state="running", is_resumable=True)
            current_run_id = str(run_info.get("run_id", "") or "")
            current_run_version = int(run_info.get("run_version", 0))
            current_signature = str(run_info.get("valid_actions_signature", "sha256:"))
            if current_run_id:
                await client.agent_register_workspace(
                    run_id=current_run_id,
                    runtime_session_id=runtime_session_id,
                    workspace_root=workspace_root,
                    workspace_fingerprint=workspace_fp,
                    git_root=workspace_git_root,
                )
        except Exception:
            current_run_id = None
            current_run_version = 0
            current_signature = "sha256:"

        console.print(f"OpenVegas Chat · {current_provider}/{current_model} · {conversation_mode}")
        console.print("Type /help for commands")
        render_status_bar(console, f"{current_provider}/{current_model}", "ready", workspace_root)

        while True:
            message = _read_chat_message()
            if not message:
                continue

            if message.startswith("/"):
                parts = message.split()
                cmd = parts[0].lower()

                if cmd == "/exit":
                    console.print("[dim]Exiting chat.[/dim]")
                    return "exit"
                if cmd == "/help":
                    _show_help()
                    continue
                if cmd == "/status":
                    console.print(
                        Panel(
                            f"[bold]Provider:[/bold] {current_provider}\n"
                            f"[bold]Model:[/bold] {current_model}\n"
                            f"[bold]Thread:[/bold] {current_thread_id or '(none)'}\n"
                            f"[bold]Run:[/bold] {current_run_id or '(none)'}\n"
                            f"[bold]Run Version:[/bold] {current_run_version}\n"
                            f"[bold]Workspace:[/bold] {workspace_root}\n"
                            f"[bold]Plan Mode:[/bold] {'on' if plan_mode else 'off'}\n"
                            f"[bold]Approval Mode:[/bold] {approval_mode}\n"
                            f"[bold]Tool Events:[/bold] {'verbose' if verbose_tool_events else 'compact'}\n"
                            "[bold]Style:[/bold] minimal (fixed)",
                            title="Chat Status",
                            border_style="cyan",
                        )
                    )
                    continue
                if cmd == "/tooling":
                    console.print(
                        Panel(
                            f"[bold]Runtime Session:[/bold] {runtime_session_id}\n"
                            f"[bold]Workspace Root:[/bold] {workspace_root}\n"
                            f"[bold]Workspace Fingerprint:[/bold] {workspace_fp}\n"
                            f"[bold]Plan Mode:[/bold] {'on' if plan_mode else 'off'}\n"
                            f"[bold]Approval Mode:[/bold] {approval_mode}\n"
                            f"[bold]Tool Events:[/bold] {'verbose' if verbose_tool_events else 'compact'}",
                            title="Tool Runtime",
                            border_style="magenta",
                        )
                    )
                    continue
                if cmd == "/style":
                    console.print("[yellow]/style is deprecated. Minimal UI style is always on.[/yellow]")
                    continue
                if cmd == "/verbose-tools":
                    if len(parts) < 2:
                        console.print("[red]Usage: /verbose-tools <on|off>[/red]")
                        continue
                    val = parts[1].strip().lower()
                    if val not in {"on", "off"}:
                        console.print("[red]Value must be on or off.[/red]")
                        continue
                    verbose_tool_events = val == "on"
                    console.print(
                        f"[green]Tool event verbosity set to {'verbose' if verbose_tool_events else 'compact'}.[/green]"
                    )
                    continue
                if cmd == "/approvals":
                    console.print(
                        Panel(
                            f"[bold]Approval Mode:[/bold] {approval_mode}\n"
                            f"{approval_rules_summary(session_approval)}",
                            title="Session Approvals",
                            border_style="yellow",
                        )
                    )
                    continue
                if cmd == "/plan":
                    if len(parts) >= 2:
                        plan_mode = parts[1].lower() in {"on", "1", "true", "yes"}
                    else:
                        plan_mode = not plan_mode
                    console.print(
                        f"[yellow]Plan mode {'enabled' if plan_mode else 'disabled'}.[/yellow] "
                        "[dim](Mutating local tools are blocked while plan mode is enabled.)[/dim]"
                    )
                    continue
                if cmd == "/approve":
                    if len(parts) < 2:
                        console.print("[red]Usage: /approve <ask|allow|exclude>[/red]")
                        continue
                    mode = parts[1].strip().lower()
                    if mode not in {"ask", "allow", "exclude"}:
                        console.print("[red]Approval mode must be ask, allow, or exclude.[/red]")
                        continue
                    approval_mode = mode
                    console.print(f"[green]Approval mode set to {approval_mode}.[/green]")
                    continue
                if cmd == "/provider":
                    if len(parts) < 2:
                        console.print("[red]Usage: /provider <openai|anthropic|gemini> [model][/red]")
                        continue
                    next_provider = parts[1].strip().lower()
                    if next_provider not in {"openai", "anthropic", "gemini"}:
                        console.print("[red]Provider must be openai, anthropic, or gemini.[/red]")
                        continue
                    next_model = parts[2].strip() if len(parts) >= 3 else get_default_model(next_provider)
                    if next_provider != current_provider and current_thread_id:
                        if not Confirm.ask(
                            "Switching provider resets context thread. Continue?",
                            default=False,
                        ):
                            continue
                        current_thread_id = None
                    current_provider = next_provider
                    current_model = next_model
                    console.print(f"[green]Provider/model set to {current_provider}/{current_model}.[/green]")
                    continue
                if cmd == "/model":
                    if len(parts) < 2:
                        console.print("[red]Usage: /model <model_id>[/red]")
                        continue
                    current_model = parts[1].strip()
                    console.print(f"[green]Model set to {current_model}.[/green]")
                    continue
                if cmd == "/ui":
                    if current_run_id:
                        try:
                            handoff_transition = await client.agent_run_transition(
                                run_id=current_run_id,
                                action="handoff",
                                expected_run_version=current_run_version,
                                expected_valid_actions_signature=current_signature,
                                idempotency_key=f"chat-handoff-{uuid.uuid4()}",
                                payload={},
                            )
                            current_run_version = int(handoff_transition.get("run_version", current_run_version))
                            current_signature = str(
                                handoff_transition.get("valid_actions_signature", current_signature)
                            )
                            handoff = await client.agent_run_handoff_check(run_id=current_run_id)
                            if handoff.get("error") == "handoff_blocked":
                                console.print(
                                    f"[red]UI handoff blocked:[/red] {handoff.get('handoff_block_reason', 'unknown')}"
                                )
                                continue
                        except APIError as e:
                            body = e.data if isinstance(e.data, dict) else {}
                            if body.get("error") == "stale_projection":
                                current_run_version = int(body.get("run_version", current_run_version))
                                current_signature = str(
                                    body.get("valid_actions_signature", current_signature)
                                )
                                console.print("[yellow]Run state refreshed. Retry /ui.[/yellow]")
                                continue
                            if body.get("error") == "handoff_blocked":
                                console.print(
                                    f"[red]UI handoff blocked:[/red] {body.get('handoff_block_reason', 'unknown')}"
                                )
                                continue
                    return "ui"

                console.print("[red]Unknown slash command. Use /help.[/red]")
                continue

            render_user_input(console, message)
            try:
                rendered = await _run_tool_loop(client, message)
                if not rendered:
                    console.print("[dim](no final assistant response)[/dim]")
                await _maybe_render_low_balance_hint(force=False)

            except APIError as e:
                body = e.data if isinstance(e.data, dict) else {}
                code = str(body.get("error", ""))
                if code in {"insufficient_balance", "balance_insufficient"}:
                    await _maybe_render_low_balance_hint(force=True)
                if code == "model_disabled":
                    suggestions: list[str] = []
                    try:
                        models_resp = await client.list_models(current_provider)
                        for m in models_resp.get("models", []):
                            if m.get("enabled"):
                                suggestions.append(str(m.get("model_id", "")))
                        suggestions = [s for s in suggestions if s][:3]
                    except Exception:
                        suggestions = []
                    console.print(f"[red]{e.detail}[/red]")
                    if suggestions:
                        console.print(
                            "[yellow]Try:[/yellow] "
                            + " ".join(f"`/model {m}`" for m in suggestions)
                        )
                    continue

                if code:
                    console.print(f"[red]{code}: {body.get('detail', e.detail)}[/red]")
                else:
                    try:
                        parsed = json.loads(str(e.detail))
                        if isinstance(parsed, dict) and parsed.get("error"):
                            console.print(f"[red]{parsed.get('error')}: {parsed.get('detail', '')}[/red]")
                        else:
                            console.print(f"[red]{e.detail}[/red]")
                    except Exception:
                        console.print(f"[red]{e.detail}[/red]")

    while True:
        outcome = run_async(_run_chat())
        if outcome == "ui":
            from openvegas.tui.prompt_ui import run_prompt_ui

            run_prompt_ui(no_render=False, render_timeout_sec=15.0)
            continue
        break


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--provider", default=None, help="Filter by provider")
def models(provider: str | None):
    """List available models and $V prices."""
    async def _models():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            data = await client.list_models(provider)
            models_list = data.get("models", [])

            table = Table(title="Available Models")
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("Name")
            table.add_column("Input $/1M", justify="right")
            table.add_column("Output $/1M", justify="right")
            table.add_column("$V In/1M", justify="right")
            table.add_column("$V Out/1M", justify="right")
            table.add_column("Status")

            for m in models_list:
                status = "[green]enabled[/green]" if m.get("enabled") else "[red]disabled[/red]"
                table.add_row(
                    m.get("provider", ""),
                    m.get("model_id", ""),
                    m.get("display_name", ""),
                    str(m.get("cost_input_per_1m", "")),
                    str(m.get("cost_output_per_1m", "")),
                    str(m.get("v_price_input_per_1m", "")),
                    str(m.get("v_price_output_per_1m", "")),
                    status,
                )
            console.print(table)
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_models())


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

@cli.group()
def store():
    """Browse and buy from the redemption store."""
    pass


@store.command("list")
def store_list():
    """Browse the redemption catalog."""
    async def _list():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            data = await client.store_list()
            items = data.get("items", {})

            table = Table(title="OpenVegas Store")
            table.add_column("ID")
            table.add_column("Name")
            table.add_column("Description")
            table.add_column("Cost ($V)", justify="right")
            table.add_column("Type")

            for item_id, item in items.items():
                table.add_row(
                    item_id,
                    item.get("name", ""),
                    item.get("description", ""),
                    str(item.get("cost_v", "")),
                    item.get("type", ""),
                )
            console.print(table)
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_list())


@store.command("buy")
@click.argument("item_id")
@click.option("--idempotency-key", default=None, help="Optional idempotency key for safe retries")
def store_buy(item_id: str, idempotency_key: str | None):
    """Buy an item from the store."""
    async def _buy():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            data = await client.store_buy(item_id=item_id, idempotency_key=idempotency_key)
            console.print(
                f"[green]Order {data.get('order_id', '')}[/green] "
                f"status={data.get('status', '')} state={data.get('state', '')}"
            )
            console.print(f"[bold]Cost:[/bold] {data.get('cost_v', '0')} $V")
            grants = data.get("grants", [])
            if grants:
                table = Table(title="Granted Inference Credits")
                table.add_column("Provider")
                table.add_column("Model")
                table.add_column("Tokens", justify="right")
                for g in grants:
                    table.add_row(g.get("provider", ""), g.get("model_id", ""), str(g.get("tokens_total", 0)))
                console.print(table)
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_buy())


@store.command("grants")
def store_grants():
    """List remaining inference grants."""
    async def _grants():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            data = await client.store_grants()
            grants = data.get("grants", [])
            if not grants:
                console.print("[dim]No inference grants found.[/dim]")
                return
            table = Table(title="Inference Grants")
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("Remaining", justify="right")
            table.add_column("Total", justify="right")
            table.add_column("Order")
            for g in grants:
                table.add_row(
                    g.get("provider", ""),
                    g.get("model_id", ""),
                    str(g.get("tokens_remaining", 0)),
                    str(g.get("tokens_total", 0)),
                    str(g.get("source_order_id", ""))[:8],
                )
            console.print(table)
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_grants())


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("game_id")
@click.option("--demo", is_flag=True, help="Verify against demo verification endpoint (non-canonical).")
def verify(game_id: str, demo: bool):
    """Verify a provably fair game outcome."""
    async def _verify():
        from openvegas.client import OpenVegasClient, APIError
        try:
            client = OpenVegasClient()
            if demo:
                data = await client.verify_demo_game(game_id)
                console.print("[bold yellow]DEMO VERIFY[/bold yellow] [dim](canonical: false)[/dim]")
                console.print(f"  Server seed hash: {data.get('server_seed_hash', '')[:16]}...")
                console.print(f"  Nonce:            {data.get('nonce', '')}")
                return

            data = await client.verify_game(game_id)
            from openvegas.rng.provably_fair import ProvablyFairRNG

            valid = ProvablyFairRNG.verify(
                data.get("server_seed", ""),
                data.get("server_seed_hash", ""),
            )
            if valid:
                console.print("[bold green]Outcome verified! Seed matches commitment.[/bold green]")
            else:
                console.print("[bold red]Verification failed! Seed does not match.[/bold red]")

            console.print(f"  Server seed: {data.get('server_seed', '')[:16]}...")
            console.print(f"  Commitment:  {data.get('server_seed_hash', '')[:16]}...")
            console.print(f"  Client seed: {data.get('client_seed', '')}")
            console.print(f"  Nonce:       {data.get('nonce', '')}")
        except APIError as e:
            console.print(f"[red]{e.detail}[/red]")

    run_async(_verify())


@cli.command("ui")
@click.option("--full", is_flag=True, help="Use legacy full-screen Textual UI mode.")
@click.option("--no-render", is_flag=True, help="Skip game animation rendering in inline UI.")
@click.option(
    "--render-timeout-sec",
    type=float,
    default=15.0,
    show_default=True,
    help="Inline UI render timeout in seconds.",
)
def interactive_ui(full: bool, no_render: bool, render_timeout_sec: float):
    """Open guided terminal UI."""
    if full:
        try:
            from openvegas.tui.wizard import run_wizard
        except Exception as e:  # pragma: no cover - runtime-only import fallback
            console.print(f"[red]Unable to load full UI mode: {e}[/red]")
            return
        run_wizard()
        return

    try:
        from openvegas.tui.prompt_ui import run_prompt_ui
    except Exception as e:  # pragma: no cover - runtime-only import fallback
        console.print(f"[red]Unable to load inline UI mode: {e}[/red]")
        return
    run_prompt_ui(no_render=no_render, render_timeout_sec=render_timeout_sec)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@cli.group("config")
def config_group():
    """Manage OpenVegas configuration."""
    pass


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a config value."""
    from openvegas.config import load_config, save_config

    config = load_config()

    if key == "default_provider":
        if value not in ("openai", "anthropic", "gemini"):
            console.print("[red]Provider must be openai, anthropic, or gemini[/red]")
            return
        config["default_provider"] = value
    elif key.startswith("default_model_"):
        provider = key.removeprefix("default_model_")
        models = config.get("default_model_by_provider", {})
        models[provider] = value
        config["default_model_by_provider"] = models
    elif key in (
        "theme",
        "animation",
        "backend_url",
        "supabase_url",
        "supabase_anon_key",
        "chat_style",
        "tool_event_density",
        "approval_ui",
    ):
        if key == "animation":
            value = value.lower() in ("true", "1", "yes")
        elif key == "chat_style":
            value = normalize_chat_style(value)
        elif key == "tool_event_density":
            value = normalize_tool_event_density(value)
        elif key == "approval_ui":
            value = normalize_approval_ui(value)
        config[key] = value
    else:
        console.print(f"[red]Unknown config key: {key}[/red]")
        return

    save_config(config)
    console.print(f"[green]Set {key} = {value}[/green]")


@config_group.command("show")
def config_show():
    """Show current configuration."""
    from openvegas.config import load_config
    import json

    config = load_config()
    # Redact sensitive fields
    display = dict(config)
    if "session" in display:
        display["session"] = {
            k: v[:8] + "..." if v else "" for k, v in display["session"].items()
        }
    for p in display.get("providers", {}):
        if "api_key" in display["providers"][p]:
            key = display["providers"][p]["api_key"]
            display["providers"][p]["api_key"] = key[:8] + "..." if key else ""

    console.print(json.dumps(display, indent=2))


if __name__ == "__main__":
    cli()
