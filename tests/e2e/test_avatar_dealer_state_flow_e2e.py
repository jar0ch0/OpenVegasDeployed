from __future__ import annotations

from openvegas.tui.avatar_state import map_lifecycle_event_to_state


def test_avatar_dealer_state_flow_sequence_contract():
    seq = [
        map_lifecycle_event_to_state("tool_start", tool_name="fs_apply_patch", status="running"),
        map_lifecycle_event_to_state("tool_result", tool_name="fs_apply_patch", status="succeeded"),
        map_lifecycle_event_to_state("finalize"),
    ]
    assert seq == ["typing", "success", "idle"]


def test_avatar_waiting_state_contract():
    assert map_lifecycle_event_to_state("approval_wait") == "waiting"
