from __future__ import annotations

from pathlib import Path

from openvegas.cli import _canonical_tool_name
from openvegas.cli import _preprocess_tool_request_for_runtime
from openvegas.cli import _promote_tool_call_for_patch_intent


def test_loop_finalize_never_crashes_on_thread_update():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "async def _force_finalize(" in src
    assert "nonlocal current_thread_id" in src


def test_patch_intent_promotes_second_fs_list_to_apply_patch():
    tool_name, args = _promote_tool_call_for_patch_intent(
        user_message="apply a tiny patch to a temp file in this repo",
        tool_name="fs_list",
        arguments={"path": "."},
        tool_observations=[{"tool_name": "fs_list"}],
    )
    assert tool_name == "fs_apply_patch"
    assert args["path"] == ".openvegas_tmp_patch.txt"


def test_unknown_tool_alias_fs_create_maps_to_apply_patch():
    assert _canonical_tool_name("fs_create") == "fs_apply_patch"


def test_unknown_tool_after_canonicalization_forces_finalize():
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "totally_unknown_tool", "arguments": {}},
        user_message="do a thing",
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert prepared is None
    assert err is not None
    assert err["error"] == "unknown_tool_name"


def test_max_iteration_forces_final_answer_no_empty_response():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "OPENVEGAS_CHAT_MAX_TOOL_STEPS" in src
    assert "Stopped after max tool iterations ({max_tool_steps})." in src
    assert 'reason="max_iterations"' in src


def test_tool_loop_processes_one_tool_call_per_step():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "tool_batch_truncated_total" in src
    assert "preprocessed_calls = preprocessed_calls[:1]" in src


def test_result_failure_attempts_tool_cancel_cleanup():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "await client.agent_tool_cancel(" in src


def test_write_patch_failure_has_regen_retry_path():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "tool_apply_patch_retry_total" in src
    assert "_prepare_write_patch(" in src
    assert "regen_args = dict(regen.get(\"arguments\", {}))" in src
    assert "_validate_patch_recovery_scope(" in src
    assert "patch_recovery_scope_expansion" in src
    assert "if await _finalize_or_continue_with_intercept(" in src


def test_fs_apply_patch_patch_recovery_from_alias_payload():
    prepared, err = _preprocess_tool_request_for_runtime(
        tool_req={
            "tool_name": "fs_apply_patch",
            "arguments": {
                "file": ".openvegas_tmp_patch.txt",
                "content": "openvegas orchestration hardening\n",
            },
        },
        user_message="apply a tiny patch to a temp file in this repo",
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert err is None
    assert prepared is not None
    assert isinstance(prepared["arguments"].get("patch"), str)
    assert prepared["arguments"]["patch"].strip()


def test_fs_search_pattern_recovery_from_alias_and_user_quoted_text():
    prepared_alias, err_alias = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "fs_search", "arguments": {"query": "result_submission_hash"}},
        user_message='search for "ignored"',
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert err_alias is None
    assert prepared_alias is not None
    assert prepared_alias["arguments"]["pattern"] == "result_submission_hash"

    prepared_quote, err_quote = _preprocess_tool_request_for_runtime(
        tool_req={"tool_name": "fs_search", "arguments": {}},
        user_message='search for "result_submission_hash" across this repo',
        model_text="",
        workspace_root=str(Path.cwd()),
        tool_observations=[],
    )
    assert err_quote is None
    assert prepared_quote is not None
    assert prepared_quote["arguments"]["pattern"] == "result_submission_hash"


def test_write_existing_path_invokes_show_diff_before_propose():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "client.ide_message(" in src
    assert "method=\"show_diff_interactive\"" in src
    assert "write_meta.get(\"existing_file\")" in src
    assert "bridge_caps.get(\"connected\")" in src
    assert "tool_show_diff_skipped_total" in src
    assert "is_valid_show_diff_payload(" in src
    assert "tool_diff_fallback_total" in src


def test_noop_preprocess_path_force_finalizes_completed():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "if any(str(obs.get(\"status\")) == \"noop\" for obs in tool_observations)" in src
    assert "reason_if_finalize=\"completed\"" in src
    assert "_continue_or_finalize_for_completion(" in src


def test_completion_gate_and_stall_reasoning_are_present():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "CompletionCriteria" in src
    assert "_continue_or_finalize_for_completion(" in src
    assert "completion_criteria_unmet_after_retries" in src
    assert "workflow_stalled_no_new_observations" in src
    assert "if did_any_execution:" in src
    assert "reason_if_finalize=\"completed\"" in src


def test_duplicate_append_same_payload_block_guard_present():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "duplicate_append_same_payload_blocked" in src
    assert "duplicate_mutation_block_total" in src
    assert "successful_append_payload_fingerprints" in src


def test_active_mutation_wait_refresh_and_timeout_reason_present():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "await _wait_for_unlock_and_refresh()" in src
    assert "await client.agent_run_get(current_run_id)" in src
    assert "active_mutation_timeout" in src


def test_streamed_shell_finalization_prompt_is_compressed():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "streamed_tools_seen" in src
    assert "If shell output was already streamed live" in src
    assert "\"output_streamed\": bool(streamed_tools_seen.get(tool_name))" in src


def test_patch_failure_regen_retry_generalized_path():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "_validate_patch_recovery_scope(" in src
    assert "patch_recovery_scope_expansion" in src
    assert "patch_recovery_failed" in src


def test_completion_gate_does_not_finalize_on_partial_artifact_creation():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "completion_criteria_unmet" in src
    assert "_continue_or_finalize_for_completion(" in src
    assert "completion_criteria_unmet_after_retries" in src


def test_show_diff_skipped_when_bridge_unavailable():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "bridge_caps" in src
    assert "tool_show_diff_skipped_total" in src
    assert "bridge_unavailable" in src
    assert "OPENVEGAS_TERMINAL_DIFF_FALLBACK" in src
    assert "review_patch_terminal(" in src
    assert "normalize_show_diff_result(" in src
    assert "tool_terminal_diff_invoked_total" in src


def test_streamed_shell_final_answer_is_compressed():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "If shell output was already streamed live" in src
    assert "\"output_streamed\": bool(streamed_tools_seen.get(tool_name))" in src


def test_active_mutation_wait_resume_succeeds_after_unlock():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "await _wait_for_unlock_and_refresh()" in src
    assert "pending_retry_tool_req" in src
    assert "continue" in src


def test_active_mutation_wait_resume_times_out_with_typed_error():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "active_mutation_timeout" in src
    assert "OPENVEGAS_ACTIVE_MUTATION_TIMEOUT_SEC" in src


def test_active_mutation_refreshes_fence_before_retry():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "await client.agent_run_get(current_run_id)" in src
    assert "_update_fence(snap if isinstance(snap, dict) else None)" in src


def test_same_intent_patch_failure_circuit_breaker_present():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "OPENVEGAS_PATCH_FAILURE_REPEAT_LIMIT" in src
    assert "patch_recovery_failed_same_intent_circuit_break" in src
    assert "tool_apply_patch_same_intent_fail_total" in src


def test_filtered_patch_becomes_canonical_signature_input():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "_filter_patch_by_accepted_hunks_with_parsed(" in src
    assert "arguments[\"patch\"] = filtered_patch" in src
    assert "call_key = _semantic_tool_signature(tool_name, arguments" in src


def test_invalid_filtered_patch_blocks_before_execution():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "_is_valid_filtered_patch(" in src
    assert "Filtered patch was invalid after hunk decisions." in src
    assert "\"error\": \"user_declined_edit\"" in src


def test_bootstrap_write_fallback_is_narrow_and_present():
    src = Path("openvegas/cli.py").read_text(encoding="utf-8")
    assert "_attempt_bootstrap_write_fallback(" in src
    assert "_is_artifact_whole_file_fallback_target(" in src
    assert "bootstrap_whole_file" in src
