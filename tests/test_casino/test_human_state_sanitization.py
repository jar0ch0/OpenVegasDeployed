from __future__ import annotations

from openvegas.casino.constants import HIDDEN_CARD_TOKEN
from openvegas.casino.human_service import _public_state_for_game


def test_public_state_hides_deck_and_blackjack_hole_card():
    state = {
        "player": [["10", "H"], ["7", "C"]],
        "dealer": [["9", "S"], ["8", "D"]],
        "deck": [["A", "S"]],
        "_server_seed": "secret",
    }

    out = _public_state_for_game("blackjack", state, "awaiting_action")
    assert "deck" not in out
    assert "_server_seed" not in out
    assert out["dealer"][0] == ["9", "S"]
    assert out["dealer"][1] == HIDDEN_CARD_TOKEN


def test_public_state_removes_shoe_for_baccarat():
    state = {
        "player": [["A", "H"], ["9", "C"]],
        "banker": [["K", "D"], ["8", "S"]],
        "shoe": [["2", "H"], ["3", "H"]],
    }
    out = _public_state_for_game("baccarat", state, "awaiting_action")
    assert "shoe" not in out


def test_public_state_hides_poker_dealer_cards_before_resolve():
    state = {
        "player": [["A", "S"], ["K", "H"]],
        "dealer": [["Q", "D"], ["J", "C"]],
        "community": [["2", "S"], ["3", "S"], ["4", "S"]],
        "deck": [["5", "S"]],
    }
    out = _public_state_for_game("poker", state, "awaiting_action")
    assert "deck" not in out
    assert out["dealer"] == [HIDDEN_CARD_TOKEN, HIDDEN_CARD_TOKEN]
