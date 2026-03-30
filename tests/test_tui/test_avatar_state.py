from __future__ import annotations

from openvegas.tui.avatar_state import map_lifecycle_event_to_state, map_tool_event_to_avatar_state


def test_avatar_state_mapping_reading():
    assert map_tool_event_to_avatar_state("fs_read", "running") == "reading"


def test_avatar_state_mapping_typing_for_mutating_tools():
    assert map_tool_event_to_avatar_state("fs_apply_patch", "running") == "typing"


def test_avatar_state_mapping_waiting():
    assert map_tool_event_to_avatar_state("fs_read", "waiting") == "waiting"


def test_avatar_state_mapping_success_and_error():
    assert map_tool_event_to_avatar_state("fs_apply_patch", "succeeded") == "success"
    assert map_tool_event_to_avatar_state("fs_apply_patch", "failed") == "error"


def test_lifecycle_mapping_finalize_idle():
    assert map_lifecycle_event_to_state("finalize") == "idle"
