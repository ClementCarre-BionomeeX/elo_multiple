from __future__ import annotations

from typing import Protocol

from elo_app.domain.matchup import Matchup
from elo_app.domain.models import Round


class GameRules(Protocol):
    def to_matchups(self, round: Round) -> list[Matchup]:  # pragma: no cover - interface only
        ...

