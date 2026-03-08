"""Tests for card renderer."""

import re
from openvegas.tui.cards import render_card, render_hand, parse_card_str


def _strip(text: str) -> str:
    return re.sub(r"\[.*?\]", "", text)


def test_render_card_utf():
    lines = render_card("K", "H", ascii_safe=False)
    assert len(lines) == 3
    raw = _strip(lines[1])
    assert "K" in raw
    assert "♥" in raw


def test_render_card_ascii():
    lines = render_card("K", "H", ascii_safe=True)
    assert len(lines) == 3
    # Pure ASCII — no Unicode box drawing
    for line in lines:
        for ch in line:
            assert ord(ch) < 128, f"Non-ASCII char '{ch}' (ord {ord(ch)}) in ASCII mode"


def test_render_card_hidden():
    for ascii_safe in [True, False]:
        lines = render_card("K", "H", ascii_safe=ascii_safe, hidden=True)
        raw = _strip(lines[1])
        assert "?" in raw
        assert "K" not in raw


def test_parse_card_str():
    assert parse_card_str("KH") == ("K", "H")
    assert parse_card_str("10S") == ("10", "S")
    assert parse_card_str("AD") == ("A", "D")


def test_render_hand_basic():
    result = render_hand(["KH", "9S"], "TEST", 19, ascii_safe=True)
    assert "TEST (19)" in result
    assert "K" in result
    assert "9" in result


def test_render_hand_positions():
    result = render_hand(["KH", "9S", "AD"], show_positions=True, ascii_safe=True)
    assert "[1]" in result
    assert "[2]" in result
    assert "[3]" in result
