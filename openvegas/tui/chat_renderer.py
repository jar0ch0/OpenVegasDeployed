"""Codex-style minimal terminal chat renderer."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.style import Style
from rich.text import Text

from openvegas.tui.qr_render import qr_half_block, qr_width


USER_BG = Style(bgcolor="grey23")
USER_PROMPT = Style(color="white", bold=True, bgcolor="grey23")
ASSISTANT_BULLET = Style(color="grey70")
ASSISTANT_TEXT = Style(color="white")
STATUS_BAR = Style(color="grey50")
DIM = Style(color="grey50")


def render_user_input(console: Console, text: str) -> None:
    """Render user message row with a subtle highlighted background."""
    line = Text()
    line.append("› ", style=USER_PROMPT)
    line.append(str(text or ""), style=USER_BG)
    line.pad_right(max(1, console.width))
    line.stylize(USER_BG)
    console.print(line)


def render_assistant(console: Console, text: str) -> None:
    """Render assistant response as plain text; no markdown parser."""
    payload = str(text or "")
    if not payload:
        return
    lines = payload.splitlines() or [payload]
    for idx, line_text in enumerate(lines):
        line = Text()
        line.append("• " if idx == 0 else "  ", style=ASSISTANT_BULLET)
        line.append(line_text, style=ASSISTANT_TEXT)
        console.print(line)


def render_tool_event(console: Console, label: str, detail: str = "") -> None:
    """Render compact, dim tool activity line."""
    text = f"  ⟳ {label}" + (f" — {detail}" if detail else "")
    console.print(Text(text, style=DIM))


def render_tool_result(console: Console, label: str, status: str) -> None:
    text = f"  ⟳ {label} — {status}"
    console.print(Text(text, style=DIM))


def render_status_bar(console: Console, model: str, budget: str, workspace: str) -> None:
    parts = f"  {model} · {budget} · {workspace}"
    console.print(Text(parts, style=STATUS_BAR))


def render_topup_hint(console: Console, hint: dict[str, object]) -> None:
    """Render low-balance top-up hint in the same minimal CLI style."""
    checkout_url = str(hint.get("checkout_url") or "")
    suggested = str(hint.get("suggested_topup_usd") or "")
    balance_v = str(hint.get("balance_v") or "")
    methods = hint.get("payment_methods_display") or []
    mode = str(hint.get("mode") or "simulated")
    qr_value = str(hint.get("qr_value") or checkout_url or "")

    console.print(Text("  ⚠ Low balance", style="yellow"))
    if balance_v:
        console.print(Text(f"  Balance: {balance_v} $V", style=ASSISTANT_TEXT))
    if suggested:
        console.print(Text(f"  Suggested top-up: ${suggested}", style=ASSISTANT_TEXT))
    if isinstance(methods, list) and methods:
        console.print(Text(f"  Methods: {', '.join(str(m) for m in methods)}", style=DIM))
    if mode == "simulated":
        console.print(Text("  [simulated checkout]", style=DIM))
    if checkout_url:
        console.print(Text(f"  -> {checkout_url}", style="cyan"))

    if qr_value and sys.stdout.isatty():
        try:
            width = qr_width(qr_value)
            if width + 4 <= console.width:
                for line in qr_half_block(qr_value).splitlines():
                    console.print(Text(f"    {line}", style=ASSISTANT_TEXT))
        except Exception:
            pass
