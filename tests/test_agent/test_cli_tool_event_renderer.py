from __future__ import annotations

from rich.console import Console

from openvegas.tui.tool_event_renderer import (
    describe_tool_action,
    friendly_tool_name,
    render_tool_event,
    render_tool_result,
)


def test_friendly_tool_name_maps_internal_tool_names():
    assert friendly_tool_name("fs_read") == "Read file"
    assert friendly_tool_name("shell_run") == "Run shell command"


def test_describe_tool_action_uses_humanized_text():
    action = describe_tool_action("fs_read", {"path": "README.md"})
    assert action == "read file README.md"
    assert "fs_read" not in action


def test_render_tool_event_outputs_bullet_and_friendly_name():
    console = Console(record=True, width=120, force_terminal=False)
    render_tool_event(
        console,
        tool_name="fs_search",
        arguments={"pattern": "result_submission_hash"},
        tool_call_id="abc-123",
        verbose=True,
    )
    out = console.export_text()
    assert "• Search code" in out
    assert "search code for" in out
    assert "abc-123" in out


def test_render_tool_result_outputs_status_line():
    console = Console(record=True, width=120, force_terminal=False)
    render_tool_result(
        console,
        tool_name="shell_run",
        result_status="succeeded",
        stdout="a\nb\n",
        stderr="",
        verbose=True,
    )
    out = console.export_text()
    assert "Run shell command: succeeded" in out
    assert "stdout lines: 2" in out

