from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List


@dataclass
class Player:
    id: str
    name: str


@dataclass
class Group:
    id: str
    name: str
    member_ids: List[str]


@dataclass
class Game:
    id: str
    name: str
    ruleset_id: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Match:
    id: str
    group_id: str
    game_id: str
    participant_ids: List[str]
    started_at: datetime
    ended_at: datetime | None = None


@dataclass
class Team:
    side_id: str
    player_ids: List[str]
    role: str = ""


@dataclass
class Outcome:
    type: str
    data: dict[str, Any]


@dataclass
class Round:
    id: str
    match_id: str
    index: int
    teams: List[Team]
    outcome: Outcome
    created_at: datetime


@dataclass
class RatingEvent:
    id: str
    group_id: str
    game_id: str
    round_id: str
    deltas: dict[str, float]
    meta: dict[str, Any]
    created_at: datetime

