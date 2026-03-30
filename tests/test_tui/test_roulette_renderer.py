from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.console import Console

from openvegas.tui import roulette_renderer


def test_window_for_width_thresholds():
    assert roulette_renderer._window_for_width(80) == 13
    assert roulette_renderer._window_for_width(65) == 13
    assert roulette_renderer._window_for_width(64) == 9
    assert roulette_renderer._window_for_width(45) == 9
    assert roulette_renderer._window_for_width(44) == 5


@pytest.mark.asyncio
async def test_animate_spin_lands_on_result(monkeypatch):
    frames_seen: list[int] = []

    original = roulette_renderer._spin_frame

    def _capture_frame(ball_index: int, *, window: int) -> str:
        frames_seen.append(ball_index)
        return original(ball_index, window=window)

    monkeypatch.setattr(roulette_renderer, "_spin_frame", _capture_frame)
    console = Console(width=80, force_terminal=True, color_system="truecolor")
    await roulette_renderer.animate_spin(console, result_number=20, frames=10)
    assert frames_seen, "expected animation to render frames"
    assert frames_seen[-1] == roulette_renderer.WHEEL_ORDER.index(20)


def test_render_result_box_lines_have_consistent_widths_unicode(monkeypatch):
    monkeypatch.setattr(roulette_renderer, "ascii_safe_mode", lambda: False)
    rendered = roulette_renderer.render_result(22, "bet_odd", False, "0.00")
    lines = rendered.splitlines()
    widths = {cell_len(line) for line in lines}
    assert len(widths) == 1


def test_render_result_box_lines_have_consistent_widths_ascii(monkeypatch):
    monkeypatch.setattr(roulette_renderer, "ascii_safe_mode", lambda: True)
    rendered = roulette_renderer.render_result(22, "bet_odd", False, "0.00")
    lines = rendered.splitlines()
    widths = {cell_len(line) for line in lines}
    assert len(widths) == 1


def test_spin_frame_does_not_include_spinner_caption():
    frame = roulette_renderer._spin_frame(0, window=13)
    assert "Wheel spinning..." not in frame.plain
