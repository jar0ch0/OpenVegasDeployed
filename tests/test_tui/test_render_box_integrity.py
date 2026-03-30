from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from openvegas.tui.cards import render_card
from openvegas.tui.roulette_renderer import render_result as render_roulette_result
from openvegas.tui.slots_renderer import render_reels


def _plain_width(line: str) -> int:
    return cell_len(Text.from_markup(line).plain)


def _assert_equal_line_widths(rendered: str) -> None:
    lines = rendered.splitlines()
    widths = {_plain_width(line) for line in lines}
    assert len(widths) == 1, f"inconsistent widths: {sorted(widths)}\n{rendered}"


def test_roulette_result_box_widths_unicode_consistent(monkeypatch):
    monkeypatch.setattr("openvegas.tui.roulette_renderer.ascii_safe_mode", lambda: False)
    _assert_equal_line_widths(render_roulette_result(22, "bet_odd", False, "0.00"))


def test_roulette_result_box_widths_ascii_consistent(monkeypatch):
    monkeypatch.setattr("openvegas.tui.roulette_renderer.ascii_safe_mode", lambda: True)
    _assert_equal_line_widths(render_roulette_result(22, "bet_odd", False, "0.00"))


def test_slots_box_widths_unicode_consistent(monkeypatch):
    monkeypatch.setattr("openvegas.tui.slots_renderer.ascii_safe_mode", lambda: False)
    _assert_equal_line_widths(render_reels(["LEMON", "BELL", "CHERRY"], hit=False))


def test_slots_box_widths_ascii_consistent(monkeypatch):
    monkeypatch.setattr("openvegas.tui.slots_renderer.ascii_safe_mode", lambda: True)
    _assert_equal_line_widths(render_reels(["LEMON", "BELL", "CHERRY"], hit=False))


def test_slots_unknown_symbol_falls_back_without_border_break(monkeypatch):
    monkeypatch.setattr("openvegas.tui.slots_renderer.ascii_safe_mode", lambda: False)
    _assert_equal_line_widths(render_reels(["UNKNOWN", "LEMON", "???"], hit=True))


def test_cards_keep_fixed_width_for_face_and_hidden_variants():
    card_10 = render_card("10", "H", ascii_safe=False, hidden=False)
    card_a = render_card("A", "S", ascii_safe=False, hidden=False)
    card_hidden = render_card("?", "S", ascii_safe=False, hidden=True)
    for lines in (card_10, card_a, card_hidden):
        widths = {_plain_width(line) for line in lines}
        assert len(widths) == 1, f"card width mismatch: {lines}"
