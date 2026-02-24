import math

import pytest

from elo_app.domain.elo_engine import DEFAULT_RATING, apply_matchup, expected, team_rating
from elo_app.domain.matchup import Matchup
from elo_app.domain.policies import DeltaDistributionPolicy, TeamRatingPolicy


def test_expected_symmetry():
    assert expected(1500, 1500) == pytest.approx(0.5)


def test_team_rating_mean():
    ratings = {"a": 1400, "b": 1600}
    assert team_rating(ratings, ["a", "b"], TeamRatingPolicy.MEAN) == pytest.approx(1500)


def test_team_rating_strength_sum():
    ratings = {"a": 1500, "b": 1600}
    q_sum = 10 ** (1500 / 400) + 10 ** (1600 / 400)
    expected_rating = 400 * math.log10(q_sum)
    assert team_rating(ratings, ["a", "b"], TeamRatingPolicy.STRENGTH_SUM) == pytest.approx(
        expected_rating
    )


def test_apply_matchup_delta_conservation():
    ratings = {pid: 1500 for pid in ["a", "b", "c", "d"]}
    matchup = Matchup(sideA=["a", "b"], sideB=["c", "d"], S=1.0, distribution="equal")
    deltas = apply_matchup(ratings, matchup, K=20)
    assert sum(deltas.values()) == pytest.approx(0.0, abs=1e-9)


def test_apply_matchup_equal_distribution_splits_evenly():
    ratings = {pid: 1500 for pid in ["a", "b", "c", "d"]}
    matchup = Matchup(sideA=["a", "b"], sideB=["c", "d"], S=1.0, distribution="equal")
    deltas = apply_matchup(ratings, matchup, K=20, distribution_policy=DeltaDistributionPolicy.EQUAL)
    assert deltas["a"] == pytest.approx(deltas["b"])
    assert deltas["c"] == pytest.approx(deltas["d"])


def test_apply_matchup_proportional_distribution_biases_stronger_players():
    ratings = {"strong": 1700, "weak": 1300, "opp1": 1500, "opp2": 1500}
    matchup = Matchup(
        sideA=["strong", "weak"],
        sideB=["opp1", "opp2"],
        S=1.0,
        distribution="proportional",
    )
    deltas = apply_matchup(
        ratings,
        matchup,
        K=20,
        distribution_policy=DeltaDistributionPolicy.PROPORTIONAL,
        team_policy=TeamRatingPolicy.STRENGTH_SUM,
    )
    assert deltas["strong"] > deltas["weak"]


def test_default_rating_used_when_missing_players():
    ratings = {"known": 1600}
    matchup = Matchup(sideA=["known", "newcomer"], sideB=["opponent"], S=0.0)
    deltas = apply_matchup(ratings, matchup, K=20)
    assert "newcomer" in deltas
    assert "opponent" in deltas


def test_empty_team_returns_default_rating_and_no_deltas():
    ratings = {}
    assert team_rating(ratings, [], TeamRatingPolicy.MEAN) == DEFAULT_RATING

    matchup = Matchup(sideA=[], sideB=["b"], S=0.0)
    deltas = apply_matchup(ratings, matchup, K=20)
    assert deltas["b"] != 0  # only opponent receives delta
    assert len(deltas) == 1


def test_invalid_policy_and_distribution_raise():
    with pytest.raises(ValueError):
        team_rating({}, ["a"], "unknown")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        apply_matchup({}, Matchup(["a"], ["b"], S=1.0, distribution="invalid"), K=20)

    from elo_app.domain import elo_engine as engine

    with pytest.raises(ValueError):
        engine._distribution_weights(["a"], {}, "bad", DEFAULT_RATING)  # type: ignore[arg-type]


def test_distribution_weights_handles_empty_and_zero_strength():
    from elo_app.domain import elo_engine as engine

    assert engine._distribution_weights([], {}, DeltaDistributionPolicy.EQUAL, DEFAULT_RATING) == []

    ratings = {"x": float("-inf"), "y": float("-inf")}
    weights = engine._distribution_weights(
        ["x", "y"], ratings, DeltaDistributionPolicy.PROPORTIONAL, DEFAULT_RATING
    )
    assert weights == pytest.approx([0.5, 0.5])


def test_apply_matchup_accepts_enum_and_fallback_distribution_policy():
    ratings = {"a": 1500, "b": 1500}
    matchup_enum = Matchup(sideA=["a"], sideB=["b"], S=1.0, distribution=DeltaDistributionPolicy.EQUAL)
    deltas_enum = apply_matchup(ratings, matchup_enum, K=10, distribution_policy=DeltaDistributionPolicy.PROPORTIONAL)
    assert "a" in deltas_enum and "b" in deltas_enum

    matchup_none = Matchup(sideA=["a"], sideB=["b"], S=0.0, distribution=None)  # type: ignore[arg-type]
    deltas_none = apply_matchup(
        ratings,
        matchup_none,
        K=10,
        distribution_policy=DeltaDistributionPolicy.PROPORTIONAL,
    )
    assert deltas_none["a"] == -deltas_none["b"]
