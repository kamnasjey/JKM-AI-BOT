from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SentRecord:
    ts: float
    symbol: str
    direction: str = ""
    timeframe: str = ""
    strategy_id: str = ""


class SignalStateStore:
    """Persistent store for signal cooldown + daily limits.

        Data model (JSON):
    {
            "schema": 2,
            "sent": { "<signal_key>": {"ts": 1730000000.0, "symbol": "EURUSD", "direction": "BUY", "timeframe": "M15", "strategy_id": "range_v1"}, ... },
            "daily": { "EURUSD|M15|range_v1": {"2025-12-20": 3, ...}, ... }
    }
    """

    def __init__(self, path: str = "state/signal_state.json") -> None:
        self.path = path
        self._lock = threading.Lock()
        self._schema = 2
        self._sent: Dict[str, SentRecord] = {}
        self._daily: Dict[str, Dict[str, int]] = {}

    @staticmethod
    def make_key(*, symbol: str, timeframe: str, strategy_id: str, direction: str) -> str:
        sym = str(symbol).upper()
        tf = str(timeframe).upper()
        sid = str(strategy_id or "").strip() or "legacy"
        d = str(direction).upper()
        return "|".join([sym, tf, sid, d])

    @staticmethod
    def make_daily_bucket(*, symbol: str, timeframe: str, strategy_id: str) -> str:
        sym = str(symbol).upper()
        tf = str(timeframe).upper()
        sid = str(strategy_id or "").strip() or "legacy"
        return "|".join([sym, tf, sid])

    def load(self) -> None:
        """Load state from disk. If missing -> empty."""
        with self._lock:
            if not os.path.exists(self.path):
                self._sent = {}
                self._daily = {}
                return

            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                self._sent = {}
                self._daily = {}
                return

            sent_raw = data.get("sent", {}) or {}
            daily_raw = data.get("daily", {}) or {}

            sent: Dict[str, SentRecord] = {}
            for k, v in sent_raw.items():
                if not isinstance(k, str) or not isinstance(v, dict):
                    continue
                ts = v.get("ts")
                symbol = v.get("symbol")
                direction = v.get("direction", "")
                timeframe = v.get("timeframe", "")
                strategy_id = v.get("strategy_id", "")
                try:
                    ts_f = float(ts)
                except Exception:
                    continue
                if not isinstance(symbol, str) or not symbol:
                    continue
                if not isinstance(direction, str):
                    direction = ""
                if not isinstance(timeframe, str):
                    timeframe = ""
                if not isinstance(strategy_id, str):
                    strategy_id = ""

                # Back-compat: schema=1/legacy entries may omit strategy_id and/or use older key formats.
                key_parts = [p for p in k.split("|") if p is not None]
                if not timeframe and len(key_parts) >= 2:
                    timeframe = key_parts[1]
                if not direction:
                    if len(key_parts) == 3:
                        direction = key_parts[2]
                    elif len(key_parts) >= 4:
                        direction = key_parts[3]

                sid = str(strategy_id or "").strip()
                if not sid:
                    if len(key_parts) >= 4 and isinstance(key_parts[2], str) and key_parts[2].strip():
                        sid = key_parts[2].strip()
                    else:
                        sid = "legacy"

                new_key = self.make_key(
                    symbol=str(symbol).upper(),
                    timeframe=str(timeframe).upper(),
                    strategy_id=sid,
                    direction=str(direction).upper(),
                )

                sent[new_key] = SentRecord(
                    ts=ts_f,
                    symbol=str(symbol).upper(),
                    direction=str(direction).upper(),
                    timeframe=str(timeframe).upper(),
                    strategy_id=sid,
                )

            daily: Dict[str, Dict[str, int]] = {}
            if isinstance(daily_raw, dict):
                for bucket, by_date in daily_raw.items():
                    if not isinstance(bucket, str) or not isinstance(by_date, dict):
                        continue

                    # Back-compat: legacy daily buckets may be "SYMBOL|TF" (no strategy_id).
                    bucket_parts = bucket.split("|")
                    if len(bucket_parts) == 2:
                        bucket = "|".join([bucket_parts[0], bucket_parts[1], "legacy"])

                    dd: Dict[str, int] = {}
                    for date_key, count in by_date.items():
                        if not isinstance(date_key, str):
                            continue
                        try:
                            dd[date_key] = int(count)
                        except Exception:
                            continue
                    if dd:
                        daily[bucket] = dd

            self._sent = sent
            self._daily = daily

    def record_sent(
        self,
        signal_key: str,
        ts: float,
        symbol: str,
        direction: str = "",
        *,
        timeframe: str = "",
        strategy_id: str = "",
    ) -> None:
        with self._lock:
            sid = str(strategy_id or "").strip() or "legacy"
            self._sent[str(signal_key)] = SentRecord(
                ts=float(ts),
                symbol=str(symbol).upper(),
                direction=str(direction or "").upper(),
                timeframe=str(timeframe or "").upper(),
                strategy_id=sid,
            )

    def can_send(self, signal_key: str, ts: float, cooldown_minutes: int) -> bool:
        cooldown_minutes = int(cooldown_minutes)
        if cooldown_minutes <= 0:
            return True

        with self._lock:
            rec = self._sent.get(str(signal_key))
            if rec is None:
                return True
            age_sec = float(ts) - float(rec.ts)
            return age_sec >= float(cooldown_minutes) * 60.0

    def increment_daily(self, symbol: str, timeframe: str, strategy_id: str, date: str) -> int:
        bucket = self.make_daily_bucket(symbol=symbol, timeframe=timeframe, strategy_id=strategy_id)
        date = str(date)
        with self._lock:
            by_date = self._daily.setdefault(bucket, {})
            by_date[date] = int(by_date.get(date, 0)) + 1
            return int(by_date[date])

    def get_daily_count(self, symbol: str, timeframe: str, strategy_id: str, date: str) -> int:
        bucket = self.make_daily_bucket(symbol=symbol, timeframe=timeframe, strategy_id=strategy_id)
        date = str(date)
        with self._lock:
            return int((self._daily.get(bucket) or {}).get(date, 0))

    def prune(self, *, older_than_days: int = 14, now_ts: Optional[float] = None) -> Tuple[int, int]:
        """Prune old sent keys and daily buckets.

        Returns: (pruned_sent, pruned_daily_entries)
        """
        older_than_days = int(older_than_days)
        if older_than_days <= 0:
            return (0, 0)

        if now_ts is None:
            now_ts = time.time()
        cutoff_ts = float(now_ts) - float(older_than_days) * 86400.0

        cutoff_date = datetime.fromtimestamp(float(now_ts), tz=timezone.utc).date() - timedelta(days=older_than_days)

        with self._lock:
            pruned_sent = 0
            for k in list(self._sent.keys()):
                if float(self._sent[k].ts) < cutoff_ts:
                    del self._sent[k]
                    pruned_sent += 1

            pruned_daily = 0
            for symbol in list(self._daily.keys()):
                by_date = self._daily.get(symbol) or {}
                for date_key in list(by_date.keys()):
                    try:
                        d = datetime.fromisoformat(date_key).date()
                    except Exception:
                        # If unparsable, keep (safer)
                        continue
                    if d < cutoff_date:
                        del by_date[date_key]
                        pruned_daily += 1
                if not by_date:
                    del self._daily[symbol]

            return (pruned_sent, pruned_daily)

    def snapshot_counts(self) -> Dict[str, int]:
        with self._lock:
            return {
                "sent_keys": len(self._sent),
                "daily_symbols": len(self._daily),
                "daily_entries": sum(len(v) for v in self._daily.values()),
            }

    def snapshot_sent(self) -> List[SentRecord]:
        """Return a snapshot list of sent records (best-effort)."""
        with self._lock:
            return [
                SentRecord(
                    ts=v.ts,
                    symbol=v.symbol,
                    direction=v.direction,
                    timeframe=v.timeframe,
                    strategy_id=v.strategy_id,
                )
                for v in self._sent.values()
            ]

    def get_sent_record(self, signal_key: str) -> Optional[SentRecord]:
        with self._lock:
            rec = self._sent.get(str(signal_key))
            if rec is None:
                return None
            return SentRecord(
                ts=rec.ts,
                symbol=rec.symbol,
                direction=rec.direction,
                timeframe=rec.timeframe,
                strategy_id=rec.strategy_id,
            )

    def save_atomic(self) -> None:
        """Atomic JSON save: write temp then os.replace."""
        with self._lock:
            data: Dict[str, Any] = {
                "schema": self._schema,
                "sent": {
                    k: {
                        "ts": v.ts,
                        "symbol": v.symbol,
                        "direction": v.direction,
                        "timeframe": v.timeframe,
                        "strategy_id": v.strategy_id,
                    }
                    for k, v in self._sent.items()
                },
                "daily": self._daily,
            }

        dir_path = os.path.dirname(self.path) or "."
        os.makedirs(dir_path, exist_ok=True)

        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, self.path)
