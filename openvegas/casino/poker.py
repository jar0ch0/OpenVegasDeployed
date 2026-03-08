"""Five-Card Draw Poker (Jacks or Better)."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from openvegas.casino.base import BaseCasinoGame
from openvegas.rng.provably_fair import ProvablyFairRNG

DECK = [
    (r, s)
    for s in ["S", "H", "D", "C"]
    for r in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
]

RANK_ORDER = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
    "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}

HAND_PAYOUTS = {
    "royal_flush": Decimal("250"),
    "straight_flush": Decimal("50"),
    "four_of_a_kind": Decimal("25"),
    "full_house": Decimal("9"),
    "flush": Decimal("6"),
    "straight": Decimal("4"),
    "three_of_a_kind": Decimal("3"),
    "two_pair": Decimal("2"),
    "jacks_or_better": Decimal("1"),
}


def evaluate_hand(cards: list) -> str:
    ranks = [c[0] for c in cards]
    suits = [c[1] for c in cards]
    values = sorted([RANK_ORDER[r] for r in ranks])
    counts = Counter(ranks)
    freq = sorted(counts.values(), reverse=True)
    is_flush = len(set(suits)) == 1
    is_straight = (
        values[-1] - values[0] == 4 and len(set(values)) == 5
    ) or values == [2, 3, 4, 5, 14]

    if is_flush and is_straight:
        if values == [10, 11, 12, 13, 14]:
            return "royal_flush"
        return "straight_flush"
    if freq == [4, 1]:
        return "four_of_a_kind"
    if freq == [3, 2]:
        return "full_house"
    if is_flush:
        return "flush"
    if is_straight:
        return "straight"
    if freq == [3, 1, 1]:
        return "three_of_a_kind"
    if freq == [2, 2, 1]:
        return "two_pair"
    if freq == [2, 1, 1, 1]:
        pair_rank = [r for r, c in counts.items() if c == 2][0]
        if RANK_ORDER[pair_rank] >= 11:
            return "jacks_or_better"
    return "nothing"


class PokerGame(BaseCasinoGame):
    game_code = "poker"
    rtp = Decimal("0.9540")

    def initial_state(self, rng, client_seed, nonce):
        deck = list(DECK)
        for i in range(len(deck) - 1, 0, -1):
            j = rng.generate_outcome(client_seed, nonce + i, i + 1)
            deck[i], deck[j] = deck[j], deck[i]
        hand = [list(deck.pop()) for _ in range(5)]
        remaining = [list(c) for c in deck]
        return {"deck": remaining, "hand": hand, "phase": "draw"}

    def apply_action(self, state, action, payload, rng, client_seed, nonce):
        if action == "hold":
            keep_positions = set(payload.get("positions", []))
            new_hand = []
            for i, card in enumerate(state["hand"]):
                if i in keep_positions:
                    new_hand.append(card)
                else:
                    new_hand.append(state["deck"].pop())
            state["hand"] = new_hand
            state["phase"] = "resolved"
        elif action == "stand":
            state["phase"] = "resolved"
        return state

    def resolve(self, state):
        cards = [tuple(c) for c in state["hand"]]
        hand_rank = evaluate_hand(cards)
        multiplier = HAND_PAYOUTS.get(hand_rank, Decimal("0"))
        display = [f"{r}{s}" for r, s in cards]
        return multiplier, {"hand": display, "rank": hand_rank}

    def valid_actions(self, state):
        if state["phase"] == "draw":
            return ["hold", "stand"]
        return []

    def is_resolved(self, state):
        return state["phase"] == "resolved"
