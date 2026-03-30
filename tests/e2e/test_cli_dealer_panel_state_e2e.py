from __future__ import annotations

from rich.console import Console

from openvegas.tui.dealer_panel import DealerPanel


def test_cli_dealer_panel_state_render_cycle():
    console = Console(record=True, width=120, force_terminal=False)
    panel = DealerPanel(console=console, enabled=True)
    panel.render("idle", "ready")
    panel.render("typing", "tool")
    panel.render("success", "done")
    panel.render("idle", "ready")

    out = console.export_text()
    assert "idle" in out
    assert "typing" in out
    assert "success" in out
