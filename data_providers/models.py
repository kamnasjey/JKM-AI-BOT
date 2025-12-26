from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True, slots=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


def validate_candles(candles: Iterable[Candle]) -> None:
    """Validate provider candle contract.

    Enforces:
    - strictly increasing timestamps
    - unique timestamps
    - high >= max(open, close) and low <= min(open, close)

    Raises:
        ValueError: If any rule is violated.
    """

    prev_ts: datetime | None = None
    seen: set[datetime] = set()

    for idx, c in enumerate(candles):
        if c.ts in seen:
            raise ValueError(f"duplicate timestamp at index={idx}: {c.ts!r}")
        seen.add(c.ts)

        if prev_ts is not None and not (c.ts > prev_ts):
            raise ValueError(
                f"timestamps must be strictly increasing; index={idx} ts={c.ts!r} prev={prev_ts!r}"
            )
        prev_ts = c.ts

        if c.high < max(c.open, c.close):
            raise ValueError(
                f"invalid OHLC at index={idx}: high < max(open, close) ({c.high} < {max(c.open, c.close)})"
            )
        if c.low > min(c.open, c.close):
            raise ValueError(
                f"invalid OHLC at index={idx}: low > min(open, close) ({c.low} > {min(c.open, c.close)})"
            )


def candles_to_cache_dicts(candles: Iterable[Candle]) -> List[Dict[str, Any]]:
    """Convert Candle objects to MarketDataCache dict format."""

    return [
        {
            "time": c.ts,
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
        }
        for c in candles
    ]
