from __future__ import annotations

from enum import Enum


class TeamRatingPolicy(str, Enum):
    MEAN = "mean"
    STRENGTH_SUM = "strength_sum"


class DeltaDistributionPolicy(str, Enum):
    EQUAL = "equal"
    PROPORTIONAL = "proportional"

