from __future__ import annotations

import io
import re

from rich.console import Console, Group
from rich.segment import Segment
from rich.text import Text

from openvegas.tui.confetti import (
    render_confetti,
    render_panel_with_confetti,
    render_result_panel,
)


def test_render_confetti_bounded_frames(monkeypatch):
    monkeypatch.setattr("openvegas.tui.confetti.time.sleep", lambda *_: None)
    console = Console(record=True)
    render_confetti(console, frames=3, width=8)
    out = console.export_text()
    assert len([line for line in out.splitlines() if line.strip()]) >= 3


def test_render_panel_with_confetti_accepts_str_and_renderable():
    c1 = Console(record=True, width=80, force_terminal=True)
    render_panel_with_confetti(c1, "hello", animate=False, confetti_pad_x=2, confetti_pad_y=3)
    out1 = c1.export_text()
    assert "hello" in out1

    c2 = Console(record=True, width=80, force_terminal=True)
    render_panel_with_confetti(c2, Text("styled", style="bold green"), animate=False)
    out2 = c2.export_text()
    assert "styled" in out2


def test_render_panel_with_confetti_has_styled_confetti_segments():
    console = Console(record=True, width=80, force_terminal=True)
    render_panel_with_confetti(console, "winner", animate=False)

    segments = list(Segment.filter_control(console._record_buffer))
    has_styled_confetti = any(
        segment.style is not None and any(ch in "*+x." for ch in segment.text)
        for segment in segments
    )
    assert has_styled_confetti is True


def test_render_panel_with_confetti_non_terminal_skips_live(monkeypatch):
    out = io.StringIO()
    console = Console(file=out, width=80, force_terminal=False)

    class _BoomLive:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Live should not be used for non-terminal consoles")

    monkeypatch.setattr("openvegas.tui.confetti.Live", _BoomLive)
    render_panel_with_confetti(console, "safe", animate=True)

    assert "safe" in out.getvalue()


def test_render_panel_with_confetti_near_full_width_frame():
    console = Console(record=True, width=80, force_terminal=True)
    render_panel_with_confetti(console, "wide", animate=False, panel_width=20)
    out = console.export_text()

    lines = [line for line in out.splitlines() if line.strip()]
    expected = max(20, console.width - 2)
    assert len(lines[0]) == expected


def test_render_panel_with_confetti_has_three_top_and_bottom_layers():
    console = Console(record=True, width=80, force_terminal=True)
    render_panel_with_confetti(console, "layers", animate=False, panel_width=20)
    out = console.export_text()

    lines = [line for line in out.splitlines() if line.strip()]

    top_layers = 0
    for line in lines:
        if re.fullmatch(r"[\*\+x\.]+", line):
            top_layers += 1
        else:
            break

    bottom_layers = 0
    for line in reversed(lines):
        if re.fullmatch(r"[\*\+x\.]+", line):
            bottom_layers += 1
        else:
            break

    assert top_layers >= 3
    assert bottom_layers >= 3


def test_render_panel_with_confetti_very_narrow_terminal_falls_back_to_plain_panel():
    console = Console(record=True, width=24, force_terminal=True)
    render_panel_with_confetti(console, "narrow fallback", animate=False)
    out = console.export_text()

    lines = [line for line in out.splitlines() if line.strip()]
    assert "narrow fallback" in out
    assert not any(re.fullmatch(r"[\*\+x\.]+", line) for line in lines)


def test_render_panel_with_confetti_handles_interrupt(monkeypatch):
    console = Console(record=True, width=80, force_terminal=True)

    class _FakeLive:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def update(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("openvegas.tui.confetti.Live", _FakeLive)
    monkeypatch.setattr("openvegas.tui.confetti.time.sleep", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    render_panel_with_confetti(console, "interrupt-safe", animate=True)
    out = console.export_text()

    assert "interrupt-safe" in out


def test_render_panel_with_confetti_uses_single_builder_for_animation_and_final(monkeypatch):
    console = Console(record=True, width=80, force_terminal=True)
    calls = {"n": 0}

    class _FakeLive:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def update(self, *_args, **_kwargs):
            return None

    def _fake_frame_builder(*_args, **_kwargs):
        calls["n"] += 1
        return Group(Text("FRAME"))

    monkeypatch.setattr("openvegas.tui.confetti.Live", _FakeLive)
    monkeypatch.setattr("openvegas.tui.confetti._build_confetti_frame", _fake_frame_builder)
    monkeypatch.setattr("openvegas.tui.confetti.time.sleep", lambda *_: None)

    render_panel_with_confetti(console, "single-builder", animate=True, frames=2, persist=True)

    assert calls["n"] == 3  # 2 animation frames + 1 final persisted frame.


def test_render_panel_with_confetti_final_frame_is_deterministic_per_call():
    c1 = Console(record=True, width=72, force_terminal=True)
    c2 = Console(record=True, width=72, force_terminal=True)

    render_panel_with_confetti(c1, "deterministic", animate=False, panel_width=22)
    render_panel_with_confetti(c2, "deterministic", animate=False, panel_width=22)

    assert c1.export_text() == c2.export_text()


def test_render_result_panel_routes_win_to_confetti(monkeypatch):
    called = {"n": 0}
    console = Console(record=True, width=80, force_terminal=True)

    def _fake_render(*_args, **_kwargs):
        called["n"] += 1

    monkeypatch.setattr("openvegas.tui.confetti.render_panel_with_confetti", _fake_render)

    render_result_panel(console, "winner", is_win=True, animation_enabled=True)
    assert called["n"] == 1


def test_render_result_panel_non_win_plain_panel():
    console = Console(record=True, width=80, force_terminal=True)
    render_result_panel(console, "no confetti", is_win=False, animation_enabled=True)
    out = console.export_text()
    assert "no confetti" in out


def test_render_panel_with_confetti_final_frame_shape_snapshot_like():
    console = Console(record=True, width=64, force_terminal=True)
    render_panel_with_confetti(
        console,
        "snapshot",
        title="Result",
        animate=False,
        confetti_pad_x=2,
        confetti_pad_y=3,
        panel_width=20,
    )
    out = console.export_text()

    lines = [line for line in out.splitlines() if line.strip()]
    assert any("snapshot" in line for line in lines)
    assert any("Result" in line for line in lines)
    assert re.fullmatch(r"[\*\+x\.]+", lines[0]) is not None
