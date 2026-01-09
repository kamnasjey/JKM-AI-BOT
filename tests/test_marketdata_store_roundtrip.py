from __future__ import annotations

import gzip
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import marketdata_store


def _mk_candles(start: datetime, n: int, minutes: int = 5):
    out = []
    t = start
    for i in range(n):
        out.append(
            {
                "time": t,
                "open": 1.0 + i,
                "high": 1.1 + i,
                "low": 0.9 + i,
                "close": 1.05 + i,
                "volume": 100 + i,
            }
        )
        t = t + timedelta(minutes=minutes)
    return out


def test_marketdata_store_upsert_and_iter(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))

    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = _mk_candles(start, 50)

    written, path = marketdata_store.upsert("EURUSD", "m5", candles, provider="MASSIVE")
    assert written == 50

    # Second upsert with overlap + one new candle
    candles2 = _mk_candles(start + timedelta(minutes=5 * 49), 2)
    written2, _ = marketdata_store.upsert("EURUSD", "m5", candles2, provider="MASSIVE")
    assert written2 == 1

    loaded = list(marketdata_store.iter_candles("EURUSD", "m5"))
    assert len(loaded) == 51
    assert loaded[0]["time"].tzinfo is not None
    assert loaded[-1]["time"] > loaded[-2]["time"]

    meta = marketdata_store.load_meta("EURUSD", "m5")
    assert meta.rows_count == 51
    assert meta.last_ts == loaded[-1]["time"]

    # File is readable gzip CSV
    p = Path(path)
    assert p.exists()
    with gzip.open(p, "rt", encoding="utf-8") as f:
        header = f.readline().strip()
    assert header.startswith("time,open,high,low,close")
