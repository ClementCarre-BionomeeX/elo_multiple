from __future__ import annotations

import math
from typing import Iterable, Mapping

from .matchup import Matchup
from .policies import DeltaDistributionPolicy, TeamRatingPolicy

DEFAULT_RATING = 1500.0


def _rating_for_player(ratings: Mapping[str, float], player_id: str, default: float) -> float:
    return float(ratings.get(player_id, default))


def team_rating(
    ratings_by_player: Mapping[str, float],
    player_ids: Iterable[str],
    policy: TeamRatingPolicy,
    default_rating: float = DEFAULT_RATING,
) -> float:
    players = list(player_ids)
    if not players:
        return default_rating

    if policy == TeamRatingPolicy.MEAN:
        total = sum(_rating_for_player(ratings_by_player, pid, default_rating) for pid in players)
        return total / len(players)

    if policy == TeamRatingPolicy.STRENGTH_SUM:
        q_values = [
            10 ** (_rating_for_player(ratings_by_player, pid, default_rating) / 400) for pid in players
        ]
        Q = sum(q_values)
        return 400 * math.log10(Q)

    raise ValueError(f"Unknown team rating policy: {policy}")


def expected(rA: float, rB: float) -> float:
    return 1 / (1 + 10 ** ((rB - rA) / 400))


def _distribution_weights(
    player_ids: list[str],
    ratings: Mapping[str, float],
    policy: DeltaDistributionPolicy,
    default_rating: float,
) -> list[float]:
    if not player_ids:
        return []

    if policy == DeltaDistributionPolicy.EQUAL:
        return [1 / len(player_ids)] * len(player_ids)

    if policy == DeltaDistributionPolicy.PROPORTIONAL:
        q_values = [
            10 ** (_rating_for_player(ratings, pid, default_rating) / 400) for pid in player_ids
        ]
        total_q = sum(q_values)
        if total_q == 0:
            return [1 / len(player_ids)] * len(player_ids)
        return [q / total_q for q in q_values]

    raise ValueError(f"Unknown distribution policy: {policy}")


def apply_matchup(
    ratings_by_player: Mapping[str, float],
    matchup: Matchup,
    K: float,
    team_policy: TeamRatingPolicy = TeamRatingPolicy.STRENGTH_SUM,
    distribution_policy: DeltaDistributionPolicy = DeltaDistributionPolicy.EQUAL,
    default_rating: float = DEFAULT_RATING,
) -> dict[str, float]:
    # Allow string or enum values in Matchup.distribution to be coerced to enum.
    if isinstance(matchup.distribution, DeltaDistributionPolicy):
        distribution = matchup.distribution
    elif isinstance(matchup.distribution, str):
        distribution = DeltaDistributionPolicy(matchup.distribution)
    else:
        distribution = distribution_policy

    rA = team_rating(ratings_by_player, matchup.sideA, team_policy, default_rating)
    rB = team_rating(ratings_by_player, matchup.sideB, team_policy, default_rating)
    exp = expected(rA, rB)

    k_eff = matchup.k_override if matchup.k_override is not None else K
    delta_team_A = k_eff * matchup.W * (matchup.S - exp)
    delta_team_B = -delta_team_A

    deltas: dict[str, float] = {}

    def _apply_delta(team_players: list[str], team_delta: float) -> None:
        if not team_players:
            return
        weights = _distribution_weights(team_players, ratings_by_player, distribution, default_rating)
        for pid, weight in zip(team_players, weights, strict=True):
            deltas[pid] = deltas.get(pid, 0.0) + team_delta * weight

    _apply_delta(matchup.sideA, delta_team_A)
    _apply_delta(matchup.sideB, delta_team_B)
    return deltas
