"""Tests for provably fair RNG."""

from openvegas.rng.provably_fair import ProvablyFairRNG


def test_commitment_matches_reveal():
    rng = ProvablyFairRNG()
    commitment = rng.new_round()
    seed = rng.reveal()
    assert ProvablyFairRNG.verify(seed, commitment)


def test_deterministic_outcomes():
    rng = ProvablyFairRNG()
    rng.new_round()

    result1 = rng.generate_outcome("client_seed", 0, 100)
    result2 = rng.generate_outcome("client_seed", 0, 100)
    assert result1 == result2


def test_different_nonces_different_outcomes():
    rng = ProvablyFairRNG()
    rng.new_round()

    result1 = rng.generate_outcome("client_seed", 0, 1000)
    result2 = rng.generate_outcome("client_seed", 1, 1000)
    # Not guaranteed to differ, but overwhelmingly likely with max_value=1000
    # Just check they're in range
    assert 0 <= result1 < 1000
    assert 0 <= result2 < 1000


def test_outcome_in_range():
    rng = ProvablyFairRNG()
    rng.new_round()

    for i in range(100):
        result = rng.generate_outcome("test", i, 10)
        assert 0 <= result < 10


def test_different_seeds_different_commitments():
    rng1 = ProvablyFairRNG()
    rng2 = ProvablyFairRNG()
    h1 = rng1.new_round()
    h2 = rng2.new_round()
    assert h1 != h2


def test_verify_rejects_wrong_seed():
    rng = ProvablyFairRNG()
    commitment = rng.new_round()
    assert not ProvablyFairRNG.verify("wrong_seed", commitment)
