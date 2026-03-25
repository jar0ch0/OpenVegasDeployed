from __future__ import annotations

from openvegas.agent.runtime_contracts import ToolPolicyDecision, evaluate_tool_policy


def test_mutating_shell_policy_modes():
    decision_ask = evaluate_tool_policy(
        tool_name="shell_run",
        shell_mode="mutating",
        approval_mode="ask",
    )
    assert decision_ask == ToolPolicyDecision.ASK

    decision_allow = evaluate_tool_policy(
        tool_name="shell_run",
        shell_mode="mutating",
        approval_mode="allow",
    )
    assert decision_allow == ToolPolicyDecision.ALLOW

    decision_exclude = evaluate_tool_policy(
        tool_name="shell_run",
        shell_mode="mutating",
        approval_mode="exclude",
    )
    assert decision_exclude == ToolPolicyDecision.EXCLUDE


def test_fs_apply_patch_policy_modes():
    decision_ask = evaluate_tool_policy(
        tool_name="fs_apply_patch",
        shell_mode=None,
        approval_mode="ask",
    )
    assert decision_ask == ToolPolicyDecision.ASK

    decision_allow = evaluate_tool_policy(
        tool_name="fs_apply_patch",
        shell_mode=None,
        approval_mode="allow",
    )
    assert decision_allow == ToolPolicyDecision.ALLOW

    decision_exclude = evaluate_tool_policy(
        tool_name="fs_apply_patch",
        shell_mode=None,
        approval_mode="exclude",
    )
    assert decision_exclude == ToolPolicyDecision.EXCLUDE


def test_read_only_tools_always_allow():
    decision = evaluate_tool_policy(
        tool_name="fs_search",
        shell_mode="read_only",
        approval_mode="exclude",
    )
    assert decision == ToolPolicyDecision.ALLOW
