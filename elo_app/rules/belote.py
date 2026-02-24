from __future__ import annotations

from dataclasses import dataclass

from elo_app.domain.matchup import Matchup
from elo_app.domain.models import Round, Team
from elo_app.rules.base import GameRules


def _find_team(teams: list[Team], side_id: str) -> Team | None:
    for team in teams:
        if team.side_id == side_id:
            return team
    return None


@dataclass
class BeloteRules(GameRules):
    k_factor: float = 20.0
    margin_weight_coeff: float = 0.5
    margin_max: float = 200.0

    def to_matchups(self, round: Round) -> list[Matchup]:
        team_a = _find_team(round.teams, "A")
        team_b = _find_team(round.teams, "B")
        if team_a is None or team_b is None:
            raise ValueError("Belote round requires teams A and B")

        if round.outcome.type != "winloss":
            raise ValueError("Belote outcome must be of type 'winloss'")

        winner = round.outcome.data.get("winner")
        margin = round.outcome.data.get("margin")

        if winner == "A":
            S = 1.0
        elif winner == "B":
            S = 0.0
        elif winner in (None, "draw"):
            S = 0.5
        else:
            raise ValueError(f"Unknown winner flag: {winner}")

        W = 1.0
        if margin is not None:
            clamped = max(0.0, min(abs(float(margin)) / self.margin_max, 1.0))
            W = 1.0 + self.margin_weight_coeff * clamped

        return [
            Matchup(
                sideA=team_a.player_ids,
                sideB=team_b.player_ids,
                S=S,
                W=W,
                k_override=self.k_factor,
                distribution="equal",
            )
        ]

