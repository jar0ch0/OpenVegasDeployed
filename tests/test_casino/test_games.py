"""Tests for casino game engines — determinism, valid actions, resolution."""

from decimal import Decimal

import pytest

from openvegas.rng.provably_fair import ProvablyFairRNG
from openvegas.casino.blackjack import BlackjackGame, hand_value
from openvegas.casino.roulette import RouletteGame
from openvegas.casino.slots import SlotsGame
from openvegas.casino.poker import PokerGame, evaluate_hand
from openvegas.casino.baccarat import BaccaratGame


@pytest.fixture
def rng():
    r = ProvablyFairRNG()
    r.new_round()
    return r


# ---- Blackjack ----

def test_blackjack_initial_state(rng):
    game = BlackjackGame()
    state = game.initial_state(rng, "seed", 0)
    assert len(state["player"]) == 2
    assert len(state["dealer"]) == 2
    assert state["phase"] in ("player_turn", "resolved")


def test_blackjack_deterministic(rng):
    game1 = BlackjackGame()
    game2 = BlackjackGame()

    rng2 = ProvablyFairRNG()
    rng2.server_seed = rng.server_seed
    rng2.server_seed_hash = rng.server_seed_hash

    s1 = game1.initial_state(rng, "seed", 0)
    s2 = game2.initial_state(rng2, "seed", 0)
    assert s1["player"] == s2["player"]
    assert s1["dealer"] == s2["dealer"]


def test_blackjack_hit_and_bust():
    game = BlackjackGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    state = game.initial_state(rng, "test", 0)

    # Hit many times until bust or stand
    for _ in range(10):
        if "hit" not in game.valid_actions(state):
            break
        state = game.apply_action(state, "hit", {}, rng, "test", 50)

    assert game.is_resolved(state) or "stand" in game.valid_actions(state)


def test_blackjack_stand_triggers_dealer():
    game = BlackjackGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    state = game.initial_state(rng, "test", 0)

    if state["phase"] == "player_turn":
        state = game.apply_action(state, "stand", {}, rng, "test", 50)
        assert state["phase"] == "resolved"
        assert game.is_resolved(state)


def test_blackjack_resolve_returns_valid_multiplier():
    game = BlackjackGame()
    rng = ProvablyFairRNG()
    rng.new_round()
    state = game.initial_state(rng, "test", 0)

    if state["phase"] == "player_turn":
        state = game.apply_action(state, "stand", {}, rng, "test", 50)

    mult, data = game.resolve(state)
    assert mult in (Decimal("0"), Decimal("1"), Decimal("2"), Decimal("2.5"))
    assert "result" in data


def test_hand_value():
    assert hand_value([("A", "S"), ("K", "H")]) == 21
    assert hand_value([("5", "S"), ("6", "H")]) == 11
    assert hand_value([("A", "S"), ("A", "H"), ("9", "D")]) == 21
    assert hand_value([("K", "S"), ("Q", "H"), ("5", "D")]) == 25


# ---- Roulette ----

def test_roulette_flow(rng):
    game = RouletteGame()
    state = game.initial_state(rng, "seed", 0)
    assert "bet_red" in game.valid_actions(state)

    state = game.apply_action(state, "bet_red", {}, rng, "seed", 0)
    assert "spin" in game.valid_actions(state)

    state = game.apply_action(state, "spin", {}, rng, "seed", 1)
    assert game.is_resolved(state)

    mult, data = game.resolve(state)
    assert mult in (Decimal("0"), Decimal("2"))
    assert 0 <= data["result"] <= 36


def test_roulette_number_bet(rng):
    game = RouletteGame()
    state = game.initial_state(rng, "seed", 0)
    state = game.apply_action(state, "bet_number", {"number": 17}, rng, "seed", 0)
    state = game.apply_action(state, "spin", {}, rng, "seed", 1)
    mult, data = game.resolve(state)
    if data["result"] == 17:
        assert mult == Decimal("36")
    else:
        assert mult == Decimal("0")


# ---- Slots ----

def test_slots_spin(rng):
    game = SlotsGame()
    state = game.initial_state(rng, "seed", 0)
    assert game.valid_actions(state) == ["spin"]

    state = game.apply_action(state, "spin", {}, rng, "seed", 0)
    assert game.is_resolved(state)
    assert len(state["reels"]) == 3

    mult, data = game.resolve(state)
    assert mult >= Decimal("0")


def test_slots_deterministic(rng):
    game = SlotsGame()
    rng2 = ProvablyFairRNG()
    rng2.server_seed = rng.server_seed
    rng2.server_seed_hash = rng.server_seed_hash

    s1 = game.initial_state(rng, "seed", 0)
    s1 = game.apply_action(s1, "spin", {}, rng, "seed", 0)

    s2 = game.initial_state(rng2, "seed", 0)
    s2 = game.apply_action(s2, "spin", {}, rng2, "seed", 0)

    assert s1["reels"] == s2["reels"]


# ---- Poker ----

def test_poker_initial_state(rng):
    game = PokerGame()
    state = game.initial_state(rng, "seed", 0)
    assert len(state["hand"]) == 5
    assert state["phase"] == "draw"


def test_poker_hold_action(rng):
    game = PokerGame()
    state = game.initial_state(rng, "seed", 0)

    state = game.apply_action(state, "hold", {"positions": [0, 2, 4]}, rng, "seed", 100)
    assert game.is_resolved(state)

    mult, data = game.resolve(state)
    assert mult >= Decimal("0")
    assert "rank" in data


def test_poker_stand_action(rng):
    game = PokerGame()
    state = game.initial_state(rng, "seed", 0)
    state = game.apply_action(state, "stand", {}, rng, "seed", 100)
    assert game.is_resolved(state)


def test_evaluate_hand():
    assert evaluate_hand([("A", "S"), ("K", "S"), ("Q", "S"), ("J", "S"), ("10", "S")]) == "royal_flush"
    assert evaluate_hand([("5", "H"), ("5", "D"), ("5", "S"), ("5", "C"), ("K", "H")]) == "four_of_a_kind"
    assert evaluate_hand([("3", "H"), ("3", "D"), ("3", "S"), ("7", "C"), ("7", "H")]) == "full_house"
    assert evaluate_hand([("2", "H"), ("5", "H"), ("8", "H"), ("J", "H"), ("A", "H")]) == "flush"
    assert evaluate_hand([("J", "S"), ("J", "H"), ("3", "D"), ("7", "C"), ("9", "S")]) == "jacks_or_better"
    assert evaluate_hand([("2", "S"), ("5", "H"), ("8", "D"), ("J", "C"), ("A", "S")]) == "nothing"


# ---- Baccarat ----

def test_baccarat_flow(rng):
    game = BaccaratGame()
    state = game.initial_state(rng, "seed", 0)
    assert "bet_player" in game.valid_actions(state)

    state = game.apply_action(state, "bet_player", {}, rng, "seed", 0)
    assert game.is_resolved(state)

    mult, data = game.resolve(state)
    assert mult >= Decimal("0")
    assert "player_total" in data
    assert "banker_total" in data


def test_baccarat_deterministic(rng):
    game1 = BaccaratGame()
    game2 = BaccaratGame()

    rng2 = ProvablyFairRNG()
    rng2.server_seed = rng.server_seed
    rng2.server_seed_hash = rng.server_seed_hash

    s1 = game1.initial_state(rng, "seed", 0)
    s1 = game1.apply_action(s1, "bet_banker", {}, rng, "seed", 0)

    s2 = game2.initial_state(rng2, "seed", 0)
    s2 = game2.apply_action(s2, "bet_banker", {}, rng2, "seed", 0)

    m1, d1 = game1.resolve(s1)
    m2, d2 = game2.resolve(s2)
    assert d1["player_total"] == d2["player_total"]
    assert d1["banker_total"] == d2["banker_total"]
    assert m1 == m2
