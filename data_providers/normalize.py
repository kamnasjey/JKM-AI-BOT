from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from engine.utils.logging_utils import log_kv

from .models import Candle

logger = logging.getLogger(__name__)

def _to_utc_open_time(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    return None


def _as_finite_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except Exception:
        return None
    if not math.isfinite(f):
        return None
    return f


def _tf_minutes(timeframe: str) -> Optional[int]:
    tf = str(timeframe or "").strip().lower()
    if not tf:
        return None
    if tf.startswith("m") and tf[1:].isdigit():
        return int(tf[1:])
    if tf.startswith("h") and tf[1:].isdigit():
        return int(tf[1:]) * 60
    if tf.startswith("d") and tf[1:].isdigit():
        return int(tf[1:]) * 1440
    # common engine formats
    if tf in ("m5", "5m", "minute_5"):
        return 5
    if tf in ("m15", "15m", "minute_15"):
        return 15
    if tf in ("h1", "1h", "hour"):
        return 60
    if tf in ("h4", "4h", "hour_4"):
        return 240
    if tf in ("d1", "1d", "day"):
        return 1440
    return None


def normalize_candles(
    candles: List[Dict[str, Any]],
    *,
    provider: str,
    symbol: str,
    timeframe: str,
    requested_limit: Optional[int] = None,
) -> List[Candle]:
    """Normalize provider candles into a single canonical format.

    Canonical rules enforced:
    - time = candle open time (UTC recommended; normalized to tz-aware UTC)
    - open/high/low/close are finite floats
    - ascending time order
    - unique timestamps (duplicates removed; last-one-wins)
    - OHLC validity: high >= max(open, close), low <= min(open, close)

    Notes:
    - Missing candles are NOT filled (to avoid changing patterns). We can optionally
      log if obvious gaps exist.
    """

    if requested_limit is not None and len(candles) < int(requested_limit):
        log_kv(
            logger,
            "PROVIDER_SHORT",
            provider=str(provider),
            symbol=str(symbol),
            tf=str(timeframe),
            requested=int(requested_limit),
            received=len(candles),
        )

    by_ts: Dict[datetime, Candle] = {}
    dropped = 0

    for c in candles or []:
        if not isinstance(c, dict):
            dropped += 1
            continue

        ts = _to_utc_open_time(c.get("time") if "time" in c else c.get("ts"))
        o = _as_finite_float(c.get("open"))
        h = _as_finite_float(c.get("high"))
        l = _as_finite_float(c.get("low"))
        cl = _as_finite_float(c.get("close"))

        if ts is None or o is None or h is None or l is None or cl is None:
            dropped += 1
            continue

        # Enforce OHLC bounds without distorting open/close.
        hi = max(h, o, cl)
        lo = min(l, o, cl)

        by_ts[ts] = Candle(
            ts=ts,
            open=float(o),
            high=float(hi),
            low=float(lo),
            close=float(cl),
        )

    out = [by_ts[t] for t in sorted(by_ts.keys())]

    if dropped:
        log_kv(
            logger,
            "PROVIDER_DROPPED",
            provider=str(provider),
            symbol=str(symbol),
            tf=str(timeframe),
            dropped=int(dropped),
        )

    # Optional gap detection (warn-only, no filling)
    try:
        minutes = _tf_minutes(timeframe)
        if minutes and len(out) >= 3:
            expected = minutes * 60
            missing = 0
            for i in range(1, len(out)):
                dt = (out[i].ts - out[i - 1].ts).total_seconds()
                if dt > expected * 1.5:
                    missing += int(round(dt / expected)) - 1
            if missing > 0:
                log_kv(
                    logger,
                    "PROVIDER_GAP",
                    provider=str(provider),
                    symbol=str(symbol),
                    tf=str(timeframe),
                    missing=int(missing),
                )
    except Exception:
        pass

    return out
