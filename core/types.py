"""core.types

Project-wide shared enums and simple types.
"""

from __future__ import annotations

from enum import Enum


class Regime(str, Enum):
    TREND_BULL = "TREND_BULL"
    TREND_BEAR = "TREND_BEAR"
    RANGE = "RANGE"
    CHOP = "CHOP"
