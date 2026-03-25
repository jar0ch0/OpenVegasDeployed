from __future__ import annotations

from rich.console import Console

from openvegas.tui.chat_renderer import (
    render_assistant,
    render_status_bar,
    render_topup_hint,
    render_user_input,
)


def test_render_user_input_prefixes_with_single_chevron():
    console = Console(record=True, width=80, force_terminal=False)
    render_user_input(console, "hello world")
    out = console.export_text()
    assert "› hello world" in out


def test_render_assistant_uses_bullet_prefix_and_plain_text():
    console = Console(record=True, width=80, force_terminal=False)
    render_assistant(console, "### Header **bold** `code`")
    out = console.export_text()
    assert "• ### Header **bold** `code`" in out


def test_render_status_bar_compact_line():
    console = Console(record=True, width=80, force_terminal=False)
    render_status_bar(console, "openai/gpt-4o-mini", "cost 0.01 $V", "~/repo")
    out = console.export_text()
    assert "openai/gpt-4o-mini · cost 0.01 $V · ~/repo" in out


def test_render_topup_hint_prints_low_balance_and_checkout_url():
    console = Console(record=True, width=120, force_terminal=False)
    render_topup_hint(
        console,
        {
            "balance_v": "123.000000",
            "suggested_topup_usd": "20.00",
            "checkout_url": "https://checkout.openvegas.local/topup/abc",
            "mode": "simulated",
            "payment_methods_display": ["Card", "PayPal"],
        },
    )
    out = console.export_text()
    assert "Low balance" in out
    assert "Suggested top-up: $20.00" in out
    assert "https://checkout.openvegas.local/topup/abc" in out
