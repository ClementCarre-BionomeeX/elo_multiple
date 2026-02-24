from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Matchup:
    sideA: List[str]
    sideB: List[str]
    S: float
    W: float = 1.0
    k_override: float | None = None
    distribution: str = "equal"

