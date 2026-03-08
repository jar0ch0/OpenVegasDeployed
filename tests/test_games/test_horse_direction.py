"""Tests for horse racing visuals — direction, colors, lane rendering."""

import re

from openvegas.games.horse_racing import (
    _horse_sprite, _render_lane, HORSE_COLORS, TRACK_WIDTHS,
)


def _strip_markup(text: str) -> str:
    """Strip Rich markup tags to get raw text."""
    return re.sub(r"\[.*?\]", "", text)


def test_sprite_has_nose_marker_ascii():
    """ASCII sprite must start with < for head direction."""
    sprite = _horse_sprite(0, ascii_safe=True)
    raw = _strip_markup(sprite)
    assert raw.startswith("<"), f"ASCII sprite '{raw}' missing < nose"


def test_sprite_has_nose_marker_utf():
    """UTF sprite must start with < for head direction."""
    sprite = _horse_sprite(0, ascii_safe=False)
    raw = _strip_markup(sprite)
    assert raw.startswith("<"), f"UTF sprite '{raw}' missing < nose"


def test_render_lane_nose_moves_left():
    """Assert nose marker index decreases with larger positions (right-to-left)."""
    nose_positions = []
    for pos in [0, 10, 30, 60]:
        lane = _render_lane(pos, 80, 0, True)
        raw = _strip_markup(lane)
        nose_idx = raw.index("<")
        nose_positions.append(nose_idx)
    assert nose_positions == sorted(nose_positions, reverse=True), f"Nose not moving left: {nose_positions}"


def test_render_lane_all_colors_utf():
    """Every horse color produces a renderable lane in UTF mode."""
    for i in range(len(HORSE_COLORS)):
        lane = _render_lane(20, 80, i, False)
        assert len(lane) > 0


def test_render_lane_all_colors_ascii():
    """Every horse color produces a renderable lane in ASCII mode."""
    for i in range(len(HORSE_COLORS)):
        lane = _render_lane(20, 80, i, True)
        raw = _strip_markup(lane)
        assert "<" in raw
