from __future__ import annotations

import io
import re

from rich.console import Console
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
    render_panel_with_confetti(c1, "hello", animate=False, confetti_pad_x=2, confetti_pad_y=1)
    out1 = c1.export_text()
    assert "hello" in out1

    c2 = Console(record=True, width=80, force_terminal=True)
    render_panel_with_confetti(c2, Text("styled", style="bold green"), animate=False)
    out2 = c2.export_text()
    assert "styled" in out2


def test_render_panel_with_confetti_non_terminal_skips_live(monkeypatch):
    out = io.StringIO()
    console = Console(file=out, width=80, force_terminal=False)

    class _BoomLive:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Live should not be used for non-terminal consoles")

    monkeypatch.setattr("openvegas.tui.confetti.Live", _BoomLive)
    render_panel_with_confetti(console, "safe", animate=True)

    assert "safe" in out.getvalue()


def test_render_panel_with_confetti_falls_back_to_plain_panel_when_not_fit(monkeypatch):
    console = Console(record=True, width=30, force_terminal=True)
    monkeypatch.setattr("openvegas.tui.confetti._fit_panel_lines", lambda *_args, **_kwargs: ([], 0))

    render_panel_with_confetti(console, "plain fallback", animate=False)
    out = console.export_text()

    assert "plain fallback" in out


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
        confetti_pad_y=1,
        panel_width=20,
    )
    out = console.export_text()

    lines = [line for line in out.splitlines() if line.strip()]
    assert any("snapshot" in line for line in lines)
    assert any("Result" in line for line in lines)
    confetti_line = lines[0]
    assert re.fullmatch(r"[\*\+x\.]+", confetti_line) is not None
