from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from openvegas.cli import _collect_tool_call_candidates
from openvegas.cli import _canonical_tool_name
from openvegas.cli import _build_completion_criteria
from openvegas.cli import CompletionCriteria
from openvegas.cli import _evaluate_completion_criteria
from openvegas.cli import _attempt_bootstrap_write_fallback
from openvegas.cli import _has_patch_intent
from openvegas.cli import _is_file_create_intent
from openvegas.cli import _is_patch_repeat_followup_intent
from openvegas.cli import _is_patch_smoke_intent
from openvegas.cli import _is_temp_patch_smoke_intent
from openvegas.cli import _mutation_retry_backoff_sec
from openvegas.cli import _pair_hunks_by_file_order_nearest
from openvegas.cli import _pairing_quality
from openvegas.cli import _parse_patch_scope
from openvegas.cli import _filter_patch_by_accepted_hunks
from openvegas.cli import _filter_patch_by_accepted_hunks_with_parsed
from openvegas.cli import _is_valid_filtered_patch
from openvegas.cli import _preprocess_tool_request_for_runtime
from openvegas.cli import _promote_tool_call_for_patch_intent
from openvegas.cli import _patch_recovery_payload
from openvegas.cli import RETRYABLE_MUTATION_ERRORS
from openvegas.cli import _semantic_tool_signature
from openvegas.cli import _search_pattern_hint_from_message
from openvegas.cli import _shell_command_hint_from_message
from openvegas.cli import _synth_patch_tool_req_for_intent
from openvegas.cli import _synthesize_patch_from_arguments
from openvegas.cli import _tool_result_reason_code
from openvegas.cli import _validate_patch_recovery_scope
from openvegas.cli import _rewrite_shell_command_for_env
from openvegas.agent.local_tools import ToolExecutionResult


def test_search_pattern_hint_prefers_quoted_token():
    msg = 'search for "result_submission_hash" across this repo and summarize where it is used'
    assert _search_pattern_hint_from_message(msg) == "result_submission_hash"


def test_search_pattern_hint_uses_search_clause_when_unquoted():
    msg = "search for result_submission_hash across this repo"
    assert _search_pattern_hint_from_message(msg) == "result_submission_hash"


def test_synthesize_patch_from_arguments_from_new_content(tmp_path: Path):
    target = tmp_path / "tmp.txt"
    target.write_text("a\n", encoding="utf-8")
    patch = _synthesize_patch_from_arguments(
        str(tmp_path),
        {"path": "tmp.txt", "new_content": "b\n"},
    )
    assert patch is not None
    assert "--- tmp.txt" in patch
    assert "+++ tmp.txt" in patch
    assert "-a" in patch
    assert "+b" in patch


def test_canonical_tool_name_maps_fs_create_to_fs_apply_patch():
    assert _canonical_tool_name("fs_create") == "fs_apply_patch"


def test_canonical_tool_name_maps_external_abi_to_internal_tools():
    assert _canonical_tool_name("Read") == "fs_read"
    assert _canonical_tool_name("Search") == "fs_search"
    assert _canonical_tool_name("Write") == "fs_apply_patch"
    assert _canonical_tool_name("Bash") == "shell_run"
    assert _canonical_tool_name("List") == "fs_list"


def test_promote_tool_call_for_patch_intent_upgrades_second_fs_list():
    name, args = _promote_tool_call_for_patch_intent(
        user_message="apply a tiny patch to a temp file in this repo",
        tool_name="fs_list",
        arguments={"path": "."},
        tool_observations=[{"tool_name": "fs_list"}],
    )
    assert _has_patch_intent("apply a tiny patch to a temp file")
    assert name == "fs_apply_patch"
    assert args["path"] == ".openvegas_tmp_patch.txt"
    assert args["new_content"].startswith("openvegas temp patch applied ")


def test_promote_tool_call_for_patch_intent_upgrades_unknown_tool():
    name, args = _promote_tool_call_for_patch_intent(
        user_message="apply a tiny patch to a temp file in this repo",
        tool_name="fs_create",
        arguments={},
        tool_observations=[],
    )
    assert name == "fs_apply_patch"
    assert args["path"] == ".openvegas_tmp_patch.txt"
    assert args["new_content"].startswith("openvegas temp patch applied ")


def test_synth_patch_tool_req_for_intent_when_no_patch_attempt_yet():
    req = _synth_patch_tool_req_for_intent(
        user_message="apply a tiny patch to a temp file in this repo",
        tool_observations=[],
    )
    assert req is not None
    assert req["tool_name"] == "fs_apply_patch"
    assert req["arguments"]["path"] == ".openvegas_tmp_patch.txt"
    assert req["arguments"]["new_content"].startswith("openvegas temp patch applied ")


def test_synth_patch_tool_req_for_create_file_intent_uses_requested_filename_and_sections():
    req = _synth_patch_tool_req_for_intent(
        user_message="Create a temp file named .openvegas_audit.md in repo root with sections: Summary, Findings, Risks, Next Steps.",
        tool_observations=[],
    )
    assert req is not None
    assert req["tool_name"] == "fs_apply_patch"
    assert req["arguments"]["path"] == ".openvegas_audit.md"
    content = req["arguments"]["new_content"]
    assert "## Summary" in content
    assert "## Findings" in content
    assert "## Risks" in content
    assert "## Next Steps" in content


def test_synth_patch_tool_req_for_intent_none_after_patch_attempt():
    req = _synth_patch_tool_req_for_intent(
        user_message="apply a tiny patch to a temp file in this repo",
        tool_observations=[{"tool_name": "fs_apply_patch"}],
    )
    assert req is None


def test_is_temp_patch_smoke_intent_true_for_temp_file_patch_prompt():
    assert _is_temp_patch_smoke_intent("apply a tiny patch to a temp file in this repo")
    assert not _is_temp_patch_smoke_intent("apply a patch to src/main.py")


def test_is_patch_smoke_intent_allows_another_patch_without_target():
    assert _is_patch_smoke_intent("apply another patch")
    assert _is_patch_smoke_intent("apply a tiny patch")
    assert not _is_patch_smoke_intent("apply a patch to openvegas/cli.py")


def test_is_patch_repeat_followup_intent():
    assert _is_patch_repeat_followup_intent("apply another one")
    assert _is_patch_repeat_followup_intent("again")
    assert _is_patch_repeat_followup_intent("one more")
    assert not _is_patch_repeat_followup_intent("run shell command again")


def test_shell_command_hint_prefers_quoted_command():
    msg = 'run shell command "ls -la | head -20" and show output as it streams'
    assert _shell_command_hint_from_message(msg) == "ls -la | head -20"


def test_collect_tool_call_candidates_parses_function_payload():
    tool_calls = [
        {
            "id": "tc1",
            "function": {
                "name": "call_local_tool",
                "arguments": '{"tool_name":"fs_search","arguments":{"pattern":"x","path":"."}}',
            },
        }
    ]
    out = _collect_tool_call_candidates(tool_calls, "")
    assert len(out) == 1
    assert out[0]["tool_name"] == "fs_search"
    assert out[0]["arguments"]["pattern"] == "x"


def test_collect_tool_call_candidates_uses_function_name_and_top_level_args():
    tool_calls = [
        {
            "id": "tc2",
            "function": {
                "name": "Write",
                "arguments": '{"filepath":"README.md","content":"x\\n"}',
            },
        }
    ]
    out = _collect_tool_call_candidates(tool_calls, "")
    assert len(out) == 1
    assert out[0]["tool_name"] == "Write"
    assert out[0]["arguments"]["filepath"] == "README.md"
    assert out[0]["arguments"]["content"] == "x\n"


def test_preprocess_tool_request_recovers_fs_search_pattern_from_user_message():
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "fs_search", "arguments": {}},
        user_message='search for "result_submission_hash" across this repo',
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["arguments"]["pattern"] == "result_submission_hash"
    assert prepared["arguments"]["path"] == "."
    assert prepared["arguments"]["max_files"] <= 500
    assert prepared["arguments"]["max_matches"] <= 200


def test_preprocess_tool_request_clamps_large_search_caps():
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={
            "tool_name": "fs_search",
            "arguments": {"pattern": "x", "max_files": 999999, "max_matches": 999999},
        },
        user_message="search for x",
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["arguments"]["max_files"] == 500
    assert prepared["arguments"]["max_matches"] == 200


def test_preprocess_tool_request_recovers_shell_command_from_user_message():
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "shell_run", "arguments": {}},
        user_message='run shell command "ls -la | head -20" and show output as it streams',
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["arguments"]["command"] == "ls -la | head -20"


def test_rewrite_shell_command_for_env_rewrites_rg_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("openvegas.cli.shutil.which", lambda cmd: None if cmd == "rg" else "/usr/bin/true")
    rewritten, reason = _rewrite_shell_command_for_env("rg 'pytest' .")
    assert rewritten.startswith("grep -R -n ")
    assert reason == "rg_unavailable_rewritten_to_grep"


def test_has_patch_intent_detects_create_file_intent():
    msg = "Create a temp file named .openvegas_audit.md in repo root"
    assert _has_patch_intent(msg)
    assert _is_file_create_intent(msg)


def test_promote_tool_call_for_create_file_intent_upgrades_fs_read():
    name, args = _promote_tool_call_for_patch_intent(
        user_message="Create a temp file named .openvegas_audit.md in repo root with sections: Summary, Findings",
        tool_name="fs_read",
        arguments={},
        tool_observations=[],
    )
    assert name == "fs_apply_patch"
    assert args["path"] == ".openvegas_audit.md"
    assert "## Summary" in args["new_content"]


def test_semantic_tool_signature_ignores_timeout_noise_for_fs_read():
    sig_a = _semantic_tool_signature("fs_read", {"path": "README.md", "max_bytes": 1024}, "read_only")
    sig_b = _semantic_tool_signature("fs_read", {"path": "README.md", "max_bytes": 4096}, "read_only")
    assert sig_a == sig_b


def test_preprocess_fs_read_recovers_relative_filename_from_user_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "openvegas-infra-play.md"
    target.write_text("hello\n", encoding="utf-8")
    monkeypatch.chdir(root)
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "fs_read", "arguments": {}},
        user_message="what do you think of your plan in here: openvegas-infra-play.md",
        model_text="",
        workspace_root=str(root),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["tool_name"] == "fs_read"
    assert prepared["arguments"]["path"] == "openvegas-infra-play.md"


def test_preprocess_fs_read_uses_hidden_filename_token_even_without_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "fs_read", "arguments": {}},
        user_message="open .openvegas_tmp_patch.txt and show current contents",
        model_text="",
        workspace_root=str(root),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["tool_name"] == "fs_read"
    assert prepared["arguments"]["path"] == ".openvegas_tmp_patch.txt"


def test_preprocess_write_existing_file_generates_patch_and_meta(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "a.md"
    target.write_text("old\n", encoding="utf-8")
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "Write", "arguments": {"filepath": "a.md", "content": "new\n"}},
        user_message="update a.md",
        model_text="",
        workspace_root=str(root),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["tool_name"] == "fs_apply_patch"
    assert "--- a.md" in prepared["arguments"]["patch"]
    assert prepared["_write_meta"]["existing_file"] is True
    assert prepared["_write_meta"]["path"] == "a.md"


def test_preprocess_write_new_file_create_path_no_existing_meta(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "Write", "arguments": {"filepath": "new.md", "content": "# hi\n"}},
        user_message="create new.md",
        model_text="",
        workspace_root=str(root),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["tool_name"] == "fs_apply_patch"
    assert "+++ new.md" in prepared["arguments"]["patch"]
    assert prepared["_write_meta"]["existing_file"] is False


def test_preprocess_write_out_of_bounds_is_blocked(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "Write", "arguments": {"filepath": "../outside.md", "content": "x\n"}},
        user_message="write file",
        model_text="",
        workspace_root=str(root),
        tool_observations=[],
    )
    assert prepared is None
    assert err is not None
    assert err["error"] == "workspace_path_out_of_bounds"


def test_preprocess_write_no_change_returns_noop(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "a.md"
    target.write_text("same\n", encoding="utf-8")
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "Write", "arguments": {"filepath": "a.md", "content": "same\n"}},
        user_message="rewrite file",
        model_text="",
        workspace_root=str(root),
        tool_observations=[],
    )
    assert prepared is None
    assert err is not None
    assert err["status"] == "noop"
    assert err["error"] == "no_change"


def test_preprocess_fs_apply_patch_preserves_patch_trailing_newline(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    patch_text = (
        "--- /dev/null\n"
        "+++ dummy.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+print('x')\n"
    )
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "fs_apply_patch", "arguments": {"patch": patch_text}},
        user_message="apply patch",
        model_text="",
        workspace_root=str(root),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["tool_name"] == "fs_apply_patch"
    assert prepared["arguments"]["patch"] == patch_text
    assert prepared["arguments"]["patch"].endswith("\n")


def test_filter_patch_by_accepted_hunks_keeps_only_selected(tmp_path: Path):
    original = "a\nb\nc\n"
    updated = "a\nx\nc\ny\n"
    patch = _synthesize_patch_from_arguments(
        str(tmp_path),
        {"path": "x.txt", "old_content": original, "new_content": updated},
    )
    assert patch is not None
    filtered = _filter_patch_by_accepted_hunks(patch, {0})
    assert filtered is not None
    assert filtered.startswith("--- x.txt")


def test_filter_and_validation_share_same_surviving_hunk_definition():
    patch = "\n".join(
        [
            "--- a/a.txt",
            "+++ b/a.txt",
            "@@ -1,1 +1,1 @@",
            "-a",
            "+b",
            "--- a/b.txt",
            "+++ b/b.txt",
            "@@ -1,1 +1,1 @@",
            "-x",
            "+y",
            "",
        ]
    )
    filtered, parsed = _filter_patch_by_accepted_hunks_with_parsed(patch, {1})
    assert filtered is not None
    assert parsed is not None
    assert _is_valid_filtered_patch(filtered, parsed_patch=parsed) is True
    assert "a/a.txt" not in filtered
    assert "b/b.txt" in filtered


def test_retryable_mutation_error_contract_and_backoff():
    assert "stale_projection" in RETRYABLE_MUTATION_ERRORS
    assert "active_mutation_in_progress" in RETRYABLE_MUTATION_ERRORS
    assert "idempotency_conflict" in RETRYABLE_MUTATION_ERRORS
    assert _mutation_retry_backoff_sec("stale_projection", 0) == 0.0
    assert _mutation_retry_backoff_sec("active_mutation_in_progress", 0) > 0.0
    assert _mutation_retry_backoff_sec("idempotency_conflict", 1) > 0.0


def test_strict_abi_mode_rejects_noncanonical_tool_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENVEGAS_TOOL_ABI_MODE", "strict")
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "fs_read", "arguments": {"path": "README.md"}},
        user_message="read file",
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert prepared is None
    assert err is not None
    assert err["error"] == "invalid_tool_arguments"


def test_strict_abi_mode_accepts_canonical_external_tool(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENVEGAS_TOOL_ABI_MODE", "strict")
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "Read", "arguments": {"filepath": "README.md"}},
        user_message="read file",
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert prepared["tool_name"] == "fs_read"


def test_patch_recovery_retry_does_not_expand_to_unrelated_files(tmp_path: Path):
    original = _synthesize_patch_from_arguments(
        str(tmp_path),
        {"path": "a.txt", "old_content": "a\n", "new_content": "b\n"},
    )
    extra = _synthesize_patch_from_arguments(
        str(tmp_path),
        {"path": "b.txt", "old_content": "x\n", "new_content": "y\n"},
    )
    regenerated = f"{(original or '').rstrip()}\n{(extra or '').lstrip()}"
    reason = _validate_patch_recovery_scope(
        original_patch=original or "",
        regenerated_patch=regenerated,
    )
    assert reason == "patch_recovery_scope_expansion"


def test_patch_recovery_retry_rejected_when_scope_exceeds_drift_tolerance(tmp_path: Path):
    original = _synthesize_patch_from_arguments(
        str(tmp_path),
        {"path": "a.txt", "old_content": ("x\n" * 20), "new_content": ("x\n" * 19) + "y\n"},
    )
    regenerated = (
        "".join(
            difflib.unified_diff(
                ("x\n" * 20).splitlines(keepends=True),
                ("x\n" * 5) + "y\n" + ("x\n" * 14),
                fromfile="a.txt",
                tofile="a.txt",
                lineterm="",
            )
        )
        + "\n"
    )
    reason = _validate_patch_recovery_scope(
        original_patch=original or "",
        regenerated_patch=regenerated,
        drift_tolerance_lines=2,
        pair_max_anchor_distance_lines=2,
    )
    assert reason == "patch_recovery_scope_expansion"


def test_patch_recovery_retry_rejected_when_touched_lines_exceed_multiplier(tmp_path: Path):
    original = _synthesize_patch_from_arguments(
        str(tmp_path),
        {"path": "a.txt", "old_content": "a\nb\n", "new_content": "a\nc\n"},
    )
    regenerated = _synthesize_patch_from_arguments(
        str(tmp_path),
        {"path": "a.txt", "old_content": "a\nb\n", "new_content": "x\n" * 30},
    )
    reason = _validate_patch_recovery_scope(
        original_patch=original or "",
        regenerated_patch=regenerated or "",
        scope_multiplier=1.0,
        absolute_slack_lines=1,
    )
    assert reason == "patch_recovery_scope_expansion"


def test_patch_recovery_retry_rejected_when_hunks_cannot_be_paired_deterministically():
    original_patch = "\n".join(
        [
            "--- a.txt",
            "+++ a.txt",
            "@@ -10,1 +10,1 @@",
            "-a",
            "+b",
            "@@ -20,1 +20,1 @@",
            "-c",
            "+d",
            "",
        ]
    )
    regenerated_patch = "\n".join(
        [
            "--- a.txt",
            "+++ a.txt",
            "@@ -15,1 +15,1 @@",
            "-a",
            "+b",
            "@@ -15,1 +15,1 @@",
            "-c",
            "+d",
            "",
        ]
    )
    original_scope = _parse_patch_scope(original_patch)
    regen_scope = _parse_patch_scope(regenerated_patch)
    assert original_scope is not None and regen_scope is not None
    pairing = _pair_hunks_by_file_order_nearest(original_scope, regen_scope)
    quality = _pairing_quality(pairing)
    assert quality.is_partial is True
    reason = _validate_patch_recovery_scope(
        original_patch=original_patch,
        regenerated_patch=regenerated_patch,
    )
    assert reason == "patch_recovery_scope_expansion"


def test_patch_recovery_retry_rejected_when_pair_quality_exceeds_threshold():
    original_patch = "\n".join(
        [
            "--- a.txt",
            "+++ a.txt",
            "@@ -1,1 +1,1 @@",
            "-a",
            "+b",
            "",
        ]
    )
    regenerated_patch = "\n".join(
        [
            "--- a.txt",
            "+++ a.txt",
            "@@ -100,1 +100,1 @@",
            "-a",
            "+b",
            "",
        ]
    )
    reason = _validate_patch_recovery_scope(
        original_patch=original_patch,
        regenerated_patch=regenerated_patch,
        pair_max_anchor_distance_lines=8,
    )
    assert reason == "patch_recovery_scope_expansion"


def test_workflow_completion_gate_requires_artifact_sections(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / ".openvegas_ml_runbook.md"
    target.write_text("# Runbook\n\n## Summary\n\nok\n", encoding="utf-8")
    msg = (
        "Create `.openvegas_ml_runbook.md` in repo root with sections: "
        "Summary, Data Contracts, Pipeline DAG"
    )
    criteria = _build_completion_criteria(msg)
    eval_result = _evaluate_completion_criteria(criteria, str(root))
    assert not eval_result.satisfied
    assert any("heading:Data Contracts" in m for m in eval_result.missing)


def test_completion_gate_uses_nonempty_section_requirement(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / ".openvegas_ml_runbook.md"
    target.write_text(
        "\n".join(
            [
                "# Runbook",
                "",
                "## Summary",
                "done",
                "",
                "## Data Contracts",
                "",
                "## Pipeline DAG",
                "graph",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    msg = (
        "Create `.openvegas_ml_runbook.md` in repo root with sections: "
        "Summary, Data Contracts, Pipeline DAG"
    )
    criteria = _build_completion_criteria(msg)
    eval_result = _evaluate_completion_criteria(criteria, str(root))
    assert not eval_result.satisfied
    assert any(":empty:" in m or ":heading:Data Contracts" in m for m in eval_result.missing)


def test_completion_eval_marks_empty_section_when_heading_present(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "runbook.md"
    target.write_text(
        "\n".join(
            [
                "# Runbook",
                "",
                "## Data Contracts",
                "",
                "## Next",
                "ok",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    criteria = CompletionCriteria(
        required_files=("runbook.md",),
        required_headings={"runbook.md": ("Data Contracts",)},
        required_nonempty_sections={"runbook.md": ("Data Contracts",)},
    )
    eval_result = _evaluate_completion_criteria(criteria, str(root))
    assert not eval_result.satisfied
    assert any(m == "runbook.md:empty:Data Contracts" for m in eval_result.missing)


def test_patch_recovery_payload_preserves_original_and_retry_diagnostics():
    original = ToolExecutionResult(
        result_status="failed",
        result_payload={
            "ok": False,
            "reason_code": "tool_execution_failed",
            "patch_failure_code": "patch_context_mismatch",
            "patch_diagnostics": {"dry_run_rc": 1, "attempts": [{"p_level": 1}]},
        },
        stdout="orig out",
        stderr="orig err",
    )
    retry = ToolExecutionResult(
        result_status="failed",
        result_payload={
            "ok": False,
            "reason_code": "tool_execution_failed",
            "patch_failure_code": "patch_context_mismatch",
            "patch_diagnostics": {"dry_run_rc": 1, "attempts": [{"p_level": 0}]},
        },
        stdout="retry out",
        stderr="retry err",
    )
    patch = "\n".join(["--- a.txt", "+++ a.txt", "@@ -1,1 +1,1 @@", "-a", "+b", ""])
    payload = _patch_recovery_payload(
        reason_code="patch_recovery_failed",
        detail="Patch recovery retry failed.",
        original_outcome=original,
        retry_outcome=retry,
        original_patch=patch,
        regenerated_patch=patch,
    )
    assert payload["reason_code"] == "patch_recovery_failed"
    assert payload["original_reason_code"] == "patch_context_mismatch"
    assert payload["retry_reason_code"] == "patch_context_mismatch"
    assert payload["target_files"] == ["a.txt"]
    assert payload["hunk_count"] == 1
    assert isinstance(payload.get("original_patch_diagnostics"), dict)
    assert isinstance(payload.get("retry_patch_diagnostics"), dict)


def test_attempt_bootstrap_write_fallback_writes_new_markdown_file(tmp_path: Path):
    result = _attempt_bootstrap_write_fallback(
        workspace_root=str(tmp_path),
        rel_path=".openvegas_ml_runbook.md",
        new_contents="# Runbook\n",
        existing_file=False,
    )
    assert result is not None
    assert result.result_status == "succeeded"
    assert (tmp_path / ".openvegas_ml_runbook.md").read_text(encoding="utf-8") == "# Runbook\n"


def test_attempt_bootstrap_write_fallback_rejects_code_files(tmp_path: Path):
    result = _attempt_bootstrap_write_fallback(
        workspace_root=str(tmp_path),
        rel_path="openvegas/cli.py",
        new_contents="print('x')\n",
        existing_file=False,
    )
    assert result is None


def test_attempt_bootstrap_write_fallback_rejects_nested_paths(tmp_path: Path):
    result = _attempt_bootstrap_write_fallback(
        workspace_root=str(tmp_path),
        rel_path="docs/runbook.md",
        new_contents="# Runbook\n",
        existing_file=False,
    )
    assert result is None


def test_attempt_bootstrap_write_fallback_allows_existing_artifact_file(tmp_path: Path):
    target = tmp_path / ".openvegas_ml_runbook.md"
    target.write_text("existing\n", encoding="utf-8")
    result = _attempt_bootstrap_write_fallback(
        workspace_root=str(tmp_path),
        rel_path=".openvegas_ml_runbook.md",
        new_contents="# Replacement\n",
        existing_file=True,
    )
    assert result is not None
    assert result.result_status == "succeeded"
    assert target.read_text(encoding="utf-8") == "# Replacement\n"


def test_tool_result_reason_code_prefers_patch_failure_code():
    result = ToolExecutionResult(
        result_status="failed",
        result_payload={"reason_code": "tool_execution_failed", "patch_failure_code": "patch_parse_invalid"},
        stdout="",
        stderr="",
    )
    assert _tool_result_reason_code(result) == "patch_parse_invalid"
