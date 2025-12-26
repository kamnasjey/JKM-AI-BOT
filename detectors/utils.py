"""Shared helper utilities for detector implementations.

Keep these helpers stateless and pure (no IO).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Literal, Optional, Sequence, Tuple

from engine_blocks import Candle


DirectionSide = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class Level:
    level: float
    lower: float
    upper: float
    kind: Literal["support", "resistance"]
    strength: int = 1


def _safe_ratio(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return a / b


def candle_range(c: Candle) -> float:
    return max(c.high - c.low, 1e-9)


def level_distance_ratio(price: float, level: float) -> float:
    return abs(price - level) / max(abs(level), 1e-9)


def is_near_level_price(price: float, level: float, tolerance_ratio: float) -> bool:
    return level_distance_ratio(price, level) <= tolerance_ratio


def is_candle_touching_level(c: Candle, level: float, tolerance_ratio: float) -> bool:
    tol = abs(level) * tolerance_ratio
    return (c.low - tol) <= level <= (c.high + tol)


def build_tp(entry: float, sl: float, direction: DirectionSide, rr: float) -> Optional[float]:
    if rr <= 0:
        return None
    if direction == "BUY":
        risk = entry - sl
        if risk <= 0:
            return None
        return entry + risk * rr
    risk = sl - entry
    if risk <= 0:
        return None
    return entry - risk * rr


def min_rr_from_profile(user_config: dict, default: float = 2.0) -> float:
    try:
        return float(user_config.get("min_rr", default))
    except Exception:
        return default


def entry_tf_from_profile(user_config: dict, default: str = "M15") -> str:
    try:
        return str(user_config.get("entry_tf", default)).upper()
    except Exception:
        return default


def find_nearest_level(price: float, levels: Sequence[float]) -> Optional[Tuple[float, float]]:
    """Return (nearest_level, distance_ratio) or None."""
    best = None
    best_d = None
    for lvl in levels:
        if not lvl:
            continue
        d = level_distance_ratio(price, lvl)
        if best_d is None or d < best_d:
            best_d = d
            best = lvl
    if best is None or best_d is None:
        return None
    return best, best_d


def last_n(candles: List[Candle], n: int) -> List[Candle]:
    if n <= 0:
        return []
    return candles[-n:] if len(candles) >= n else candles[:]


def body_size(c: Candle) -> float:
    return abs(c.close - c.open)


def bullish(c: Candle) -> bool:
    return c.close >= c.open


def bearish(c: Candle) -> bool:
    return c.close <= c.open


def simple_slope(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return values[-1] - values[0]


def within(a: float, b: float, tolerance_ratio: float) -> bool:
    """Check if a and b are within tolerance_ratio of b."""
    return abs(a - b) <= abs(b) * tolerance_ratio
