"""Tests for Horse Racing game."""

import hashlib
from decimal import Decimal

import pytest

from openvegas.games.horse_racing import (
    HorseRacing,
    RACE_MODEL_VERSION,
    _normalize_checkpoints,
)
from openvegas.rng.provably_fair import ProvablyFairRNG

FIXED_SEED_CORPUS = [
    (
        hashlib.sha256(f"server-{i}".encode()).hexdigest(),
        hashlib.sha256(f"client-{i}".encode()).hexdigest(),
    )
    for i in range(100)
]


@pytest.fixture
def rng():
    r = ProvablyFairRNG()
    r.new_round()
    return r


def _rng_for_server_seed(server_seed: str) -> ProvablyFairRNG:
    r = ProvablyFairRNG()
    r.server_seed = server_seed
    r.server_seed_hash = hashlib.sha256(server_seed.encode()).hexdigest()
    return r


async def _resolve_fixed(server_seed: str, client_seed: str) -> dict:
    game = HorseRacing(num_horses=8)
    bet = {
        "game_id": "fixed",
        "player_id": "user-1",
        "amount": 10.0,
        "type": "win",
        "horse": 1,
    }
    result = await game.resolve(bet, _rng_for_server_seed(server_seed), client_seed, 0)
    return result.outcome_data


def _lead_changes(checkpoints: list[dict[int, float]]) -> int:
    leaders: list[int] = []
    for cp in checkpoints:
        leaders.append(max(cp.items(), key=lambda kv: kv[1])[0])
    return sum(1 for a, b in zip(leaders, leaders[1:]) if a != b)


@pytest.mark.asyncio
async def test_race_produces_result(rng):
    game = HorseRacing(num_horses=6)
    bet = {
        "game_id": "test-1",
        "player_id": "user-1",
        "amount": 10.0,
        "type": "win",
        "horse": 1,
    }
    result = await game.resolve(bet, rng, "client_seed", 0)
    assert result.game_id == "test-1"
    assert result.provably_fair is True
    assert len(result.outcome_data["finish_order"]) == 6
    assert result.bet_amount == Decimal("10.0")


@pytest.mark.asyncio
async def test_race_deterministic(rng):
    game1 = HorseRacing(num_horses=6)
    game2 = HorseRacing(num_horses=6)

    bet = {
        "game_id": "test-1",
        "player_id": "user-1",
        "amount": 5.0,
        "type": "win",
        "horse": 1,
    }

    # Same seed + nonce = same result
    r1 = await game1.resolve(bet, rng, "client_seed", 0)

    rng2 = ProvablyFairRNG()
    rng2.server_seed = rng.server_seed
    rng2.server_seed_hash = rng.server_seed_hash

    r2 = await game2.resolve(bet, rng2, "client_seed", 0)
    assert r1.outcome_data["finish_order"] == r2.outcome_data["finish_order"]


@pytest.mark.asyncio
async def test_validate_bet():
    game = HorseRacing(num_horses=8)
    assert await game.validate_bet({"horse": 1, "type": "win", "amount": 5})
    assert await game.validate_bet({"horse": 8, "type": "place", "amount": 1})
    assert not await game.validate_bet({"horse": 0, "type": "win", "amount": 5})
    assert not await game.validate_bet({"horse": 9, "type": "win", "amount": 5})
    assert not await game.validate_bet({"horse": 1, "type": "invalid", "amount": 5})


@pytest.mark.asyncio
async def test_resolve_has_checkpoints_and_model_version(rng):
    game = HorseRacing(num_horses=6)
    bet = {
        "game_id": "test-1",
        "player_id": "user-1",
        "amount": 10.0,
        "type": "win",
        "horse": 1,
    }
    result = await game.resolve(bet, rng, "client_seed", 0)
    assert "checkpoints" in result.outcome_data
    assert len(result.outcome_data["checkpoints"]) > 0
    assert "finish_order_nums" in result.outcome_data
    assert len(result.outcome_data["finish_order_nums"]) == len(result.outcome_data["horses"])
    assert result.outcome_data["race_model_version"] == RACE_MODEL_VERSION


@pytest.mark.asyncio
async def test_final_checkpoint_matches_finish_order(rng):
    """Final checkpoint positions must be ordered consistently with finish_order_nums."""
    game = HorseRacing(num_horses=6)
    bet = {
        "game_id": "test-1",
        "player_id": "user-1",
        "amount": 10.0,
        "type": "win",
        "horse": 1,
    }
    result = await game.resolve(bet, rng, "client_seed", 0)
    final_cp = result.outcome_data["checkpoints"][-1]
    finish_nums = result.outcome_data["finish_order_nums"]
    # Winner (index 0) should have highest position in final checkpoint
    for i in range(len(finish_nums) - 1):
        assert final_cp[finish_nums[i]] >= final_cp[finish_nums[i + 1]], (
            f"Rank {i} (horse {finish_nums[i]}) at {final_cp[finish_nums[i]]} "
            f"should be >= rank {i+1} (horse {finish_nums[i+1]}) at {final_cp[finish_nums[i+1]]}"
        )


def test_normalize_checkpoints_handles_stringified_keys():
    normalized = _normalize_checkpoints([
        {"1": "12.5", "2": 11, "bad": "x"},
        {1: 13.75, "3": "10.25"},
    ])
    assert normalized[0][1] == 12.5
    assert normalized[0][2] == 11.0
    assert 3 in normalized[1]


@pytest.mark.asyncio
async def test_replay_data_has_lead_changes_for_fixed_seed_set():
    races_with_visible_lead_changes = 0
    for server_seed, client_seed in FIXED_SEED_CORPUS:
        data = await _resolve_fixed(server_seed, client_seed)
        checkpoints = _normalize_checkpoints(data["checkpoints"])
        if _lead_changes(checkpoints) >= 2:
            races_with_visible_lead_changes += 1

    assert races_with_visible_lead_changes >= int(len(FIXED_SEED_CORPUS) * 0.40)


@pytest.mark.asyncio
async def test_favorite_win_rate_not_extreme_for_fixed_seed_set():
    favorite_wins = 0
    for server_seed, client_seed in FIXED_SEED_CORPUS:
        data = await _resolve_fixed(server_seed, client_seed)
        favorite = min(
            data["horses"],
            key=lambda h: (float(h["odds"]), h["number"]),
        )["number"]
        winner = data["finish_order_nums"][0]
        if favorite == winner:
            favorite_wins += 1

    favorite_win_rate = favorite_wins / len(FIXED_SEED_CORPUS)
    assert favorite_win_rate < 0.85


@pytest.mark.asyncio
async def test_start_order_not_locked_to_finish_for_fixed_seed_set():
    same_order_count = 0
    for server_seed, client_seed in FIXED_SEED_CORPUS:
        data = await _resolve_fixed(server_seed, client_seed)
        start_order = [
            h["number"] for h in sorted(
                data["horses"],
                key=lambda h: (float(h["odds"]), h["number"]),
            )
        ]
        if start_order == data["finish_order_nums"]:
            same_order_count += 1

    same_order_rate = same_order_count / len(FIXED_SEED_CORPUS)
    assert same_order_rate <= 0.30
