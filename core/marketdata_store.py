from __future__ import annotations

import csv
import gzip
import json
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from core.atomic_io import atomic_write_text


def _state_dir() -> Path:
    return Path(os.getenv("STATE_DIR") or "state")


def _marketdata_root() -> Path:
    return _state_dir() / "marketdata"


def _symbol_dir(symbol: str) -> Path:
    return _marketdata_root() / str(symbol).upper()


def _canon_tf(timeframe: str) -> str:
    tf = str(timeframe or "").strip().lower()
    if tf in {"5m", "m5", "minute_5"}:
        return "m5"
    if tf in {"15m", "m15", "minute_15"}:
        return "m15"
    if tf in {"1h", "h1", "hour"}:
        return "h1"
    if tf in {"4h", "h4", "hour_4"}:
        return "h4"
    if tf in {"1d", "d1", "day"}:
        return "d1"
    return tf or "m5"


def _data_path(symbol: str, timeframe: str) -> Path:
    tf = _canon_tf(timeframe)
    return _symbol_dir(symbol) / f"{tf}.csv.gz"


def _meta_path(symbol: str, timeframe: str) -> Path:
    tf = _canon_tf(timeframe)
    return _symbol_dir(symbol) / f"{tf}.meta.json"


def _dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _iso_to_dt(s: str) -> Optional[datetime]:
    if not isinstance(s, str):
        return None
    st = s.strip()
    if not st:
        return None
    if st.endswith("Z"):
        st = st[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(st)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class MarketDataMeta:
    last_ts: Optional[datetime]
    rows_count: int


def load_meta(symbol: str, timeframe: str) -> MarketDataMeta:
    p = _meta_path(symbol, timeframe)
    if not p.exists():
        return MarketDataMeta(last_ts=None, rows_count=0)

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return MarketDataMeta(last_ts=None, rows_count=0)

    if not isinstance(raw, dict):
        return MarketDataMeta(last_ts=None, rows_count=0)

    last = _iso_to_dt(str(raw.get("last_ts") or ""))
    try:
        rows = int(raw.get("rows_count") or 0)
    except Exception:
        rows = 0
    return MarketDataMeta(last_ts=last, rows_count=max(0, rows))


def save_meta(symbol: str, timeframe: str, *, last_ts: Optional[datetime], rows_count: int) -> None:
    p = _meta_path(symbol, timeframe)
    p.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": 1,
        "symbol": str(symbol).upper(),
        "timeframe": _canon_tf(timeframe),
        "last_ts": _dt_to_iso(last_ts) if last_ts is not None else None,
        "rows_count": int(max(0, int(rows_count))),
        "updated_at": _dt_to_iso(datetime.now(timezone.utc)),
    }
    atomic_write_text(p, json.dumps(payload, ensure_ascii=False))


def iter_candles(symbol: str, timeframe: str) -> Iterator[Dict[str, Any]]:
    """Stream candles from persisted store.

    Each yielded candle is a dict with `time` as datetime (UTC) plus OHLCV.
    """

    p = _data_path(symbol, timeframe)
    if not p.exists():
        return iter(())

    def _gen() -> Iterator[Dict[str, Any]]:
        try:
            with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not isinstance(row, dict):
                        continue
                    t = _iso_to_dt(str(row.get("time") or ""))
                    if t is None:
                        continue
                    try:
                        out: Dict[str, Any] = {
                            "time": t,
                            "open": float(row.get("open") or "nan"),
                            "high": float(row.get("high") or "nan"),
                            "low": float(row.get("low") or "nan"),
                            "close": float(row.get("close") or "nan"),
                        }
                        vol = row.get("volume")
                        if vol not in (None, ""):
                            out["volume"] = float(vol)
                        yield out
                    except Exception:
                        continue
        except Exception:
            return

    return _gen()


def load_range(
    symbol: str,
    timeframe: str,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in iter_candles(symbol, timeframe):
        t = c.get("time")
        if not isinstance(t, datetime):
            continue
        if start is not None and not (t >= start):
            continue
        if end is not None and not (t <= end):
            continue
        out.append(c)
    return out


def load_tail(symbol: str, timeframe: str, *, limit: int = 5000) -> List[Dict[str, Any]]:
    """Load last N candles from gz-csv efficiently (single pass)."""
    buf: deque[Dict[str, Any]] = deque(maxlen=max(1, int(limit)))
    for c in iter_candles(symbol, timeframe):
        buf.append(c)
    return list(buf)


def append(symbol: str, timeframe: str, candles: Iterable[Dict[str, Any]]) -> Tuple[int, str]:
    """Append candles to per-symbol store.

    Expects each candle dict has at least: time (datetime), open/high/low/close.
    Returns (written_count, path).
    """

    sym = str(symbol).upper()
    tf = _canon_tf(timeframe)
    p = _data_path(sym, tf)
    p.parent.mkdir(parents=True, exist_ok=True)

    meta = load_meta(sym, tf)
    last_ts = meta.last_ts

    # Track rows_count for meta.
    rows_count = int(meta.rows_count)

    # Filter & serialize (CSV rows).
    rows: List[Dict[str, str]] = []
    new_last: Optional[datetime] = last_ts

    for c in candles:
        if not isinstance(c, dict):
            continue
        t = c.get("time")
        if not isinstance(t, datetime):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        t = t.astimezone(timezone.utc)
        if last_ts is not None and not (t > last_ts):
            continue

        try:
            row: Dict[str, str] = {
                "time": _dt_to_iso(t),
                "open": str(float(c.get("open"))),
                "high": str(float(c.get("high"))),
                "low": str(float(c.get("low"))),
                "close": str(float(c.get("close"))),
                "volume": "",
            }
            if c.get("volume") is not None:
                row["volume"] = str(float(c.get("volume")))
        except Exception:
            continue

        rows.append(row)
        new_last = t

    if not rows:
        return (0, str(p))

    # Append a gzip member (safe; gzip readers handle concatenated members).
    file_exists = p.exists()
    with gzip.open(p, "at", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
        if not file_exists or p.stat().st_size == 0:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)
            rows_count += 1

    save_meta(sym, tf, last_ts=new_last, rows_count=rows_count)
    return (len(rows), str(p))
