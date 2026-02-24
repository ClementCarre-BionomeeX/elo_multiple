from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from elo_app.domain.models import Outcome, Round, Team


def make_round(
    teams: List[Team],
    outcome: Outcome,
    match_id: str = "match-1",
    index: int = 1,
) -> Round:
    return Round(
        id=f"round-{index}",
        match_id=match_id,
        index=index,
        teams=teams,
        outcome=outcome,
        created_at=datetime.now(timezone.utc),
    )
