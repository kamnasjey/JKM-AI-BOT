from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services.models import SignalEvent

DB_PATH = os.getenv("USER_DB_PATH", "user_profiles.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_signals_db() -> None:
    conn = _get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_key TEXT UNIQUE,
            user_id TEXT,
            pair TEXT,
            direction TEXT,
            timeframe TEXT,
            entry REAL,
            sl REAL,
            tp REAL,
            rr REAL,
            strategy_name TEXT,
            tz_offset_hours INTEGER DEFAULT 0,
            generated_at TEXT,
            status TEXT DEFAULT 'pending',
            resolved_at TEXT,
            resolved_price REAL,
            meta_json TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_user_status ON signals(user_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_user_time ON signals(user_id, generated_at)")
    conn.commit()
    conn.close()


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dt_to_iso(dt: datetime) -> str:
    return _to_utc(dt).isoformat()


def _iso_to_dt(s: str) -> datetime:
    # Accept both naive and tz-aware ISO.
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _make_signal_key(
    *,
    user_id: str,
    pair: str,
    direction: str,
    timeframe: str,
    entry: float,
    sl: float,
    tp: float,
    generated_at_iso: str,
) -> str:
    raw = f"{user_id}|{pair}|{direction}|{timeframe}|{entry:.10f}|{sl:.10f}|{tp:.10f}|{generated_at_iso}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def record_signal(
    *,
    user_id: str,
    signal: SignalEvent,
    strategy_name: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Persist a signal only if it was actually sent to the user."""
    init_signals_db()

    generated_at = _dt_to_iso(getattr(signal, "generated_at", datetime.utcnow()))
    signal_key = _make_signal_key(
        user_id=str(user_id),
        pair=str(signal.pair),
        direction=str(signal.direction),
        timeframe=str(signal.timeframe),
        entry=float(signal.entry),
        sl=float(signal.sl),
        tp=float(signal.tp),
        generated_at_iso=generated_at,
    )

    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO signals (
                signal_key, user_id, pair, direction, timeframe,
                entry, sl, tp, rr,
                strategy_name, tz_offset_hours,
                generated_at, status, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                signal_key,
                str(user_id),
                str(signal.pair),
                str(signal.direction),
                str(signal.timeframe),
                float(signal.entry),
                float(signal.sl),
                float(signal.tp),
                float(signal.rr),
                (str(strategy_name) if strategy_name else None),
                int(getattr(signal, "tz_offset_hours", 0) or 0),
                generated_at,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM signals WHERE signal_key=?", (signal_key,)).fetchone()
        return int(row["id"]) if row else None
    finally:
        conn.close()


def list_pending_signals(user_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    init_signals_db()
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE user_id=? AND status='pending'
            ORDER BY generated_at ASC
            LIMIT ?
            """,
            (str(user_id), int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_signal_resolution(
    *,
    signal_id: int,
    status: str,
    resolved_at: datetime,
    resolved_price: Optional[float] = None,
) -> None:
    init_signals_db()
    conn = _get_connection()
    try:
        conn.execute(
            """
            UPDATE signals
            SET status=?, resolved_at=?, resolved_price=?
            WHERE id=?
            """,
            (str(status), _dt_to_iso(resolved_at), (float(resolved_price) if resolved_price is not None else None), int(signal_id)),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_metrics(user_id: str) -> Dict[str, Any]:
    init_signals_db()
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) as cnt
            FROM signals
            WHERE user_id=?
            GROUP BY status
            """,
            (str(user_id),),
        ).fetchall()
        counts = {r["status"]: int(r["cnt"]) for r in rows}
        wins = int(counts.get("win", 0))
        losses = int(counts.get("loss", 0))
        pending = int(counts.get("pending", 0))
        expired = int(counts.get("expired", 0))
        decided = wins + losses
        winrate = (wins / decided * 100.0) if decided else 0.0
        return {
            "user_id": str(user_id),
            "wins": wins,
            "losses": losses,
            "pending": pending,
            "expired": expired,
            "total": wins + losses + pending + expired,
            "decided": decided,
            "winrate": winrate,
        }
    finally:
        conn.close()


def _hit_order_for_candle(
    *,
    direction: str,
    candle_low: float,
    candle_high: float,
    sl: float,
    tp: float,
) -> Optional[str]:
    """Return 'win' or 'loss' if either boundary hit in this candle.

    Conservative rule:
    - If both SL and TP touched in same candle -> treat as loss.
    """
    direction = str(direction).upper()

    if direction == "BUY":
        sl_hit = candle_low <= sl
        tp_hit = candle_high >= tp
        if sl_hit and tp_hit:
            return "loss"
        if sl_hit:
            return "loss"
        if tp_hit:
            return "win"
        return None

    # SELL
    sl_hit = candle_high >= sl
    tp_hit = candle_low <= tp
    if sl_hit and tp_hit:
        return "loss"
    if sl_hit:
        return "loss"
    if tp_hit:
        return "win"
    return None


def evaluate_pending_signals_for_user(
    *,
    user_id: str,
    max_age_hours: int = 168,
) -> Dict[str, Any]:
    """Resolve pending signals as win/loss using cached candles.

    Uses cache-first data (5m) and resamples to the signal timeframe.
    """
    from market_data_cache import market_cache
    from resample_5m import resample

    pending = list_pending_signals(str(user_id), limit=400)
    if not pending:
        return {"evaluated": 0, "resolved": 0, "expired": 0}

    now_utc = datetime.now(timezone.utc)
    evaluated = 0
    resolved = 0
    expired = 0

    for row in pending:
        evaluated += 1
        signal_id = int(row["id"])
        pair = str(row["pair"])
        direction = str(row["direction"]).upper()
        timeframe = str(row["timeframe"]).upper()
        sl = float(row["sl"])
        tp = float(row["tp"])

        try:
            generated_at = _iso_to_dt(str(row["generated_at"]))
        except Exception:
            # Can't parse; expire it.
            update_signal_resolution(signal_id=signal_id, status="expired", resolved_at=now_utc)
            expired += 1
            continue

        if max_age_hours > 0 and (now_utc - generated_at) > timedelta(hours=int(max_age_hours)):
            update_signal_resolution(signal_id=signal_id, status="expired", resolved_at=now_utc)
            expired += 1
            continue

        raw_5m = market_cache.get_candles(pair)
        if not raw_5m or len(raw_5m) < 20:
            continue

        try:
            tf_candles = resample(raw_5m, timeframe)
        except Exception:
            continue

        # Find candles after signal time.
        for c in tf_candles:
            t = c.get("time")
            if not isinstance(t, datetime):
                continue
            ct = _to_utc(t) if t.tzinfo else t.replace(tzinfo=timezone.utc)
            if ct <= generated_at:
                continue

            low = float(c.get("low"))
            high = float(c.get("high"))
            hit = _hit_order_for_candle(
                direction=direction,
                candle_low=low,
                candle_high=high,
                sl=sl,
                tp=tp,
            )
            if hit == "win":
                update_signal_resolution(signal_id=signal_id, status="win", resolved_at=ct, resolved_price=tp)
                resolved += 1
                break
            if hit == "loss":
                update_signal_resolution(signal_id=signal_id, status="loss", resolved_at=ct, resolved_price=sl)
                resolved += 1
                break

    return {"evaluated": evaluated, "resolved": resolved, "expired": expired}
