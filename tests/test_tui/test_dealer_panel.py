from __future__ import annotations

from rich.console import Console

from openvegas.tui.dealer_panel import DealerPanel


def test_dealer_panel_renders_state_line():
    console = Console(record=True, width=120, force_terminal=False)
    panel = DealerPanel(console=console, enabled=True)
    panel.render("typing", "tool running")
    out = console.export_text()
    assert "Dealer" in out
    assert "typing" in out


def test_dealer_panel_ascii_safe_fallback(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_CLI_ASCII_SAFE", "1")
    console = Console(record=True, width=120, force_terminal=False)
    panel = DealerPanel(console=console, enabled=True)
    panel.render("success", "done")
    out = console.export_text()
    assert "Dealer" in out
    assert "success" in out
    assert "[ok]" in out or "[OK]" in out
