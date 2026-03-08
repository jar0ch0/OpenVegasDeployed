"""Blackjack — single-deck, dealer stands on 17."""

from __future__ import annotations

from decimal import Decimal

from openvegas.casino.base import BaseCasinoGame
from openvegas.rng.provably_fair import ProvablyFairRNG

DECK = [
    (r, s)
    for s in ["S", "H", "D", "C"]
    for r in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
]


def hand_value(cards: list) -> int:
    total, aces = 0, 0
    for rank, _ in cards:
        if rank in ("J", "Q", "K"):
            total += 10
        elif rank == "A":
            aces += 1
            total += 11
        else:
            total += int(rank)
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def cards_str(cards: list) -> list[str]:
    return [f"{r}{s}" for r, s in cards]


class BlackjackGame(BaseCasinoGame):
    game_code = "blackjack"
    rtp = Decimal("0.9950")

    def initial_state(self, rng: ProvablyFairRNG, client_seed: str, nonce: int) -> dict:
        deck = list(DECK)
        for i in range(len(deck) - 1, 0, -1):
            j = rng.generate_outcome(client_seed, nonce + i, i + 1)
            deck[i], deck[j] = deck[j], deck[i]

        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]

        state = {
            "deck": [list(c) for c in deck],
            "player": [list(c) for c in player],
            "dealer": [list(c) for c in dealer],
            "phase": "player_turn",
        }

        if hand_value(player) == 21:
            state["phase"] = "resolved"

        return state

    def apply_action(self, state, action, payload, rng, client_seed, nonce):
        if state["phase"] != "player_turn":
            return state

        if action == "hit":
            state["player"].append(state["deck"].pop())
            if hand_value(state["player"]) > 21:
                state["phase"] = "resolved"
        elif action == "stand":
            while hand_value(state["dealer"]) < 17:
                state["dealer"].append(state["deck"].pop())
            state["phase"] = "resolved"

        return state

    def resolve(self, state):
        pv = hand_value(state["player"])
        dv = hand_value(state["dealer"])
        pc = cards_str(state["player"])
        dc = cards_str(state["dealer"])
        data = {"player": pv, "dealer": dv, "player_cards": pc, "dealer_cards": dc}

        if pv == 21 and len(state["player"]) == 2:
            if dv == 21 and len(state["dealer"]) == 2:
                return Decimal("1"), {**data, "result": "push"}
            return Decimal("2.5"), {**data, "result": "blackjack"}

        if pv > 21:
            return Decimal("0"), {**data, "result": "bust"}
        if dv > 21:
            return Decimal("2"), {**data, "result": "dealer_bust"}
        if pv > dv:
            return Decimal("2"), {**data, "result": "win"}
        if pv == dv:
            return Decimal("1"), {**data, "result": "push"}
        return Decimal("0"), {**data, "result": "loss"}

    def valid_actions(self, state):
        if state["phase"] == "player_turn":
            return ["hit", "stand"]
        return []

    def is_resolved(self, state):
        return state["phase"] == "resolved"
