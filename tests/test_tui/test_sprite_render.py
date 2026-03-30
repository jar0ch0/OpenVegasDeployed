from __future__ import annotations

from pathlib import Path

from openvegas.tui.sprite_render import TerminalSpriteRenderer


def test_terminal_sprite_renderer_disabled_without_truecolor(monkeypatch):
    monkeypatch.delenv("COLORTERM", raising=False)
    renderer = TerminalSpriteRenderer(Path("missing.png"))
    assert renderer.enabled() is False
    assert renderer.reason == "terminal_no_truecolor"


def test_terminal_sprite_renderer_reports_missing_dependency_or_sheet(monkeypatch, tmp_path):
    monkeypatch.setenv("COLORTERM", "truecolor")
    renderer = TerminalSpriteRenderer(tmp_path / "missing.png")
    assert renderer.enabled() is False
    assert renderer.reason in {"pillow_missing", "sheet_missing"}

