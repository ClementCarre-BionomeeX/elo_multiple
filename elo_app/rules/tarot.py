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
class TarotRules(GameRules):
    k_factor: float = 16.0
    margin_weight_coeff: float = 0.5
    margin_max: float = 300.0

    def to_matchups(self, round: Round) -> list[Matchup]:
        att_team = _find_team(round.teams, "ATT")
        def_team = _find_team(round.teams, "DEF")
        if att_team is None or def_team is None:
            raise ValueError("Tarot round requires ATT and DEF teams")

        if round.outcome.type != "contract":
            raise ValueError("Tarot outcome must be of type 'contract'")

        success = round.outcome.data.get("success")
        margin = round.outcome.data.get("margin")

        if success is True:
            S = 1.0
        elif success is False:
            S = 0.0
        else:
            raise ValueError("Tarot outcome requires boolean 'success'")

        W = 1.0
        if margin is not None:
            clamped = max(0.0, min(abs(float(margin)) / self.margin_max, 1.0))
            W = 1.0 + self.margin_weight_coeff * clamped

        return [
            Matchup(
                sideA=att_team.player_ids,
                sideB=def_team.player_ids,
                S=S,
                W=W,
                k_override=self.k_factor,
                distribution="equal",
            )
        ]

