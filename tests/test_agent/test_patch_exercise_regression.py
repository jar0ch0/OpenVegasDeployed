from __future__ import annotations

from pathlib import Path

import pytest

from openvegas.agent.local_tools import execute_tool_request
from openvegas.tui.diff_reviewer import (
    filter_patch_by_accepted_hunks,
    is_valid_filtered_patch,
    parse_unified_patch,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "patch_exercises"


def _normalize_diff_path(raw: str) -> str:
    token = str(raw or "").strip()
    if token.startswith("a/") or token.startswith("b/"):
        token = token[2:]
    return token


def _build_old_side_baseline(root: Path, patch_text: str) -> None:
    parsed = parse_unified_patch(patch_text)
    assert parsed.parse_error is None

    for file_patch in parsed.files:
        old_header = str(file_patch.old_header or "").strip()
        if not old_header.startswith("--- "):
            continue
        old_path = _normalize_diff_path(old_header[4:])
        if old_path == "/dev/null":
            continue

        target = root / old_path
        target.parent.mkdir(parents=True, exist_ok=True)

        max_old_line = 0
        for hunk in file_patch.hunks:
            max_old_line = max(max_old_line, int(hunk.old_start) + max(0, int(hunk.old_count)) - 1)

        if max_old_line <= 0:
            target.write_text("", encoding="utf-8")
            continue

        lines = ["\n"] * max_old_line
        for hunk in file_patch.hunks:
            cursor = max(0, int(hunk.old_start) - 1)
            for body_line in hunk.body_lines:
                if body_line.startswith("\\"):
                    continue
                if not body_line:
                    continue
                marker = body_line[0]
                payload = body_line[1:]
                if marker in {" ", "-"}:
                    if cursor >= len(lines):
                        lines.extend(["\n"] * (cursor - len(lines) + 1))
                    lines[cursor] = payload
                    cursor += 1

        target.write_text("".join(lines), encoding="utf-8")


def _load_patch(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("patch_name", "expected_status", "expected_patch_failure_code"),
    [
        ("patch_1_renderer_many_hunks.patch", "succeeded", None),
        ("patch_2_multifile_physics.patch", "succeeded", None),
        ("patch_3_new_file_audio.patch", "succeeded", None),
        ("patch_4_edge_cases_strings.patch", "succeeded", None),
        ("patch_5_massive_refactor_ecs.patch", "succeeded", None),
    ],
)
def test_patch_exercise_expected_outcomes(
    tmp_path: Path,
    patch_name: str,
    expected_status: str,
    expected_patch_failure_code: str | None,
):
    patch_text = _load_patch(patch_name)
    parsed = parse_unified_patch(patch_text)
    assert parsed.parse_error is None

    _build_old_side_baseline(tmp_path, patch_text)
    for rel in parsed.target_files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)

    outcome = execute_tool_request(
        workspace_root=str(tmp_path),
        tool_name="fs_apply_patch",
        arguments={"patch": patch_text},
        shell_mode="workspace_write",
        timeout_sec=30,
    )
    assert outcome.result_status == expected_status

    payload = outcome.result_payload if isinstance(outcome.result_payload, dict) else {}
    assert payload.get("patch_failure_code") == expected_patch_failure_code

    if expected_status == "succeeded":
        files_targeted = payload.get("files_targeted")
        assert isinstance(files_targeted, list) and len(files_targeted) >= 1
        assert int(payload.get("hunks_applied", 0)) >= 1
    else:
        diagnostics = payload.get("patch_diagnostics")
        assert isinstance(diagnostics, dict)
        assert int(diagnostics.get("dry_run_rc", -1)) != 0


def test_patch1_partial_accept_hunks_applies_successfully(tmp_path: Path):
    patch_text = _load_patch("patch_1_renderer_many_hunks.patch")
    parsed = parse_unified_patch(patch_text)
    assert parsed.parse_error is None
    assert parsed.hunks_total == 18

    filtered_text, filtered_parsed = filter_patch_by_accepted_hunks(patch_text, {3, 7, 12})
    assert filtered_text is not None
    assert filtered_parsed is not None
    assert filtered_parsed.hunks_total == 3
    assert is_valid_filtered_patch(filtered_parsed) is True

    _build_old_side_baseline(tmp_path, patch_text)
    outcome = execute_tool_request(
        workspace_root=str(tmp_path),
        tool_name="fs_apply_patch",
        arguments={"patch": filtered_text},
        shell_mode="workspace_write",
        timeout_sec=30,
    )
    assert outcome.result_status == "succeeded"
    payload = outcome.result_payload if isinstance(outcome.result_payload, dict) else {}
    assert int(payload.get("hunks_applied", 0)) == 3


def test_patch2_cross_file_partial_accept_filters_to_header_and_applies(tmp_path: Path):
    patch_text = _load_patch("patch_2_multifile_physics.patch")
    parsed = parse_unified_patch(patch_text)
    assert parsed.parse_error is None
    assert len(parsed.target_files) == 3

    accepted_hunks = {
        h.hunk_index for h in parsed.hunks if h.file_path == "include/physics/rigid_body.h"
    }
    filtered_text, filtered_parsed = filter_patch_by_accepted_hunks(patch_text, accepted_hunks)
    assert filtered_text is not None
    assert filtered_parsed is not None
    assert list(filtered_parsed.target_files) == ["include/physics/rigid_body.h"]
    assert is_valid_filtered_patch(filtered_parsed) is True

    _build_old_side_baseline(tmp_path, patch_text)
    outcome = execute_tool_request(
        workspace_root=str(tmp_path),
        tool_name="fs_apply_patch",
        arguments={"patch": filtered_text},
        shell_mode="workspace_write",
        timeout_sec=30,
    )
    assert outcome.result_status == "succeeded"
