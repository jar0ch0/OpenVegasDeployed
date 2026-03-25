from __future__ import annotations

from rich.console import Console

import openvegas.tui.approval_menu as approval_menu
from openvegas.tui.approval_menu import (
    ApprovalDecision,
    SessionApprovalState,
    action_scope_for,
    apply_approval_decision,
    choose_approval,
    should_auto_allow,
)


def test_choose_approval_supports_expected_choices():
    console = Console(record=True, width=120, force_terminal=False)
    decision = choose_approval(
        tool_name="fs_apply_patch",
        arguments={"path": ".openvegas_tmp_patch.txt"},
        action_label="apply patch to .openvegas_tmp_patch.txt",
        console=console,
        selector_fn=lambda _: ApprovalDecision.ALWAYS_THIS_SCOPE,
    )
    assert decision == ApprovalDecision.ALWAYS_THIS_SCOPE
    rendered = console.export_text()
    assert "Yes" in rendered
    assert "Always yes for this action type" in rendered
    assert "No, do something different" in rendered
    assert "Select option" not in rendered


def test_session_approval_always_this_scope_bypasses_future_prompts():
    state = SessionApprovalState()
    scope = action_scope_for("fs_apply_patch", {})
    assert not should_auto_allow(state, scope)
    apply_approval_decision(state, scope, ApprovalDecision.ALWAYS_THIS_SCOPE)
    assert should_auto_allow(state, scope)
    assert not should_auto_allow(state, action_scope_for("shell_run", {"command": "ls"}))


def test_action_scope_for_shell_network_detection():
    assert action_scope_for("shell_run", {"command": "curl https://example.com"}) == "shell_networked"
    assert action_scope_for("shell_run", {"command": "ls -la"}) == "shell_local"


def test_choose_approval_non_tty_fallback(monkeypatch):
    monkeypatch.setattr(approval_menu, "_is_tty", lambda: False)
    monkeypatch.setattr(approval_menu.Confirm, "ask", lambda *args, **kwargs: False)
    console = Console(record=True, width=120, force_terminal=False)
    decision = choose_approval(
        tool_name="fs_apply_patch",
        arguments={"path": "temp.txt"},
        action_label="apply patch to temp.txt",
        console=console,
    )
    assert decision == ApprovalDecision.DENY_AND_REPLAN
