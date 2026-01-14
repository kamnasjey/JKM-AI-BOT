# market_data_cache.py
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, timezone
import json
from pathlib import Path

from core.atomic_io import atomic_write_text

class MarketDataCache:
    """
    Thread-safe in-memory cache for market data (Candles).
    Stores data as 5m candles.
    Also caches resampled candles for performance.
    """
    
    def __init__(self, max_len: int = 5000):
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._tf_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}  # (symbol, tf) -> {"last_ts": ..., "candles": ...}
        self._rev: Dict[str, int] = {}  # per-symbol revision, bumps when any candle changes
        self._lock = threading.RLock()
        self._max_len = max_len
        self._stats: Dict[str, int] = {
            "market_hit": 0,
            "market_miss": 0,
            "resample_hit": 0,
            "resample_miss": 0,
        }

    def get_cache_stats(self) -> Dict[str, int]:
        """Return a snapshot of cache hit/miss counters."""
        with self._lock:
            return dict(self._stats)

    def reset_cache_stats(self) -> None:
        with self._lock:
            for k in list(self._stats.keys()):
                self._stats[k] = 0

    def upsert_candles(self, symbol: str, candles: List[Dict[str, Any]]) -> None:
        """
        Merge new candles into the cache. 
        Handles deduplication by 'time'.
        Input candles MUST have 'time' as datetime objects (preferably UTC).
        """
        if not candles:
            return

        def _to_utc_dt(v: Any) -> Optional[datetime]:
            if v is None:
                return None
            if isinstance(v, datetime):
                if v.tzinfo is None:
                    v = v.replace(tzinfo=timezone.utc)
                return v.astimezone(timezone.utc)
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return None
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                try:
                    dt = datetime.fromisoformat(s)
                except Exception:
                    return None
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            if isinstance(v, (int, float)):
                # epoch seconds or ms
                try:
                    ts = float(v)
                except Exception:
                    return None
                if ts > 1e12:
                    ts = ts / 1000.0
                try:
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                except Exception:
                    return None
            return None

        def _canon(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            if not isinstance(c, dict):
                return None
            ts = _to_utc_dt(c.get("time"))
            if ts is None:
                return None
            try:
                o = float(c.get("open"))
                h = float(c.get("high"))
                l = float(c.get("low"))
                cl = float(c.get("close"))
            except Exception:
                return None
            out: Dict[str, Any] = {
                "time": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(cl),
            }
            if c.get("volume") is not None:
                try:
                    out["volume"] = float(c.get("volume"))
                except Exception:
                    pass
            return out

        def _same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
            keys = ("open", "high", "low", "close")
            for k in keys:
                if float(a.get(k)) != float(b.get(k)):
                    return False
            va = a.get("volume")
            vb = b.get("volume")
            if va is None and vb is None:
                return True
            if va is None or vb is None:
                return False
            return float(va) == float(vb)

        with self._lock:
            sym = symbol.upper()
            current = self._cache.get(sym, [])
            prev_last_ts = current[-1]["time"] if current else None

            data_map: Dict[datetime, Dict[str, Any]] = {}
            changed = False

            # Canonicalize existing cache entries.
            for existing in current:
                cc = _canon(existing)
                if cc is None:
                    changed = True
                    continue
                # If coercion changes tz awareness or merges duplicates, treat as change.
                prev = data_map.get(cc["time"])
                if prev is not None and not _same(prev, cc):
                    changed = True
                data_map[cc["time"]] = cc

            # Merge incoming candles.
            for incoming in candles:
                cc = _canon(incoming)
                if cc is None:
                    continue
                prev = data_map.get(cc["time"])
                if prev is None:
                    changed = True
                elif not _same(prev, cc):
                    changed = True
                data_map[cc["time"]] = cc

            merged = sorted(data_map.values(), key=lambda x: x["time"])
            if len(merged) > self._max_len:
                merged = merged[-self._max_len:]

            self._cache[sym] = merged

            new_last_ts = merged[-1]["time"] if merged else None
            newer_appended = (
                prev_last_ts is None
                or (new_last_ts is not None and prev_last_ts is not None and new_last_ts > prev_last_ts)
            )
            if changed or newer_appended:
                self._rev[sym] = int(self._rev.get(sym, 0)) + 1
                self._invalidate_tf_cache(sym)

    def get_candles(self, symbol: str) -> List[Dict[str, Any]]:
        with self._lock:
            sym = symbol.upper()
            candles = self._cache.get(sym, [])
            if candles:
                self._stats["market_hit"] += 1
            else:
                self._stats["market_miss"] += 1
            # Return a copy to be safe
            return list(candles)
            
    def get_candles_since(self, symbol: str, since_ts: datetime) -> List[Dict[str, Any]]:
        """
        Get all candles strictly after the given timestamp.
        """
        with self._lock:
            all_candles = self._cache.get(symbol.upper(), [])
            if not all_candles:
                return []
            
            # Filter
            res = [c for c in all_candles if c['time'] > since_ts]
            return res

    def get_all_symbols(self) -> List[str]:
        with self._lock:
            return list(self._cache.keys())
            
    def get_last_timestamp(self, symbol: str) -> Optional[datetime]:
        with self._lock:
            candles = self._cache.get(symbol.upper())
            if candles:
                return candles[-1]['time']
            return None
    
    def _invalidate_tf_cache(self, symbol: str) -> None:
        """Invalidate all resampled caches for a symbol."""
        # Must be called within lock
        sym = symbol.upper()
        keys_to_remove = [k for k in self._tf_cache.keys() if k[0] == sym]
        for key in keys_to_remove:
            del self._tf_cache[key]
    
    def get_resampled(
        self,
        symbol: str,
        timeframe: str,
        *,
        with_meta: bool = False,
    ) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
        """
        Get resampled candles for a symbol at given timeframe.
        Uses cache to avoid redundant resampling.
        
        Args:
            symbol: Symbol name (e.g., "EURUSD")
            timeframe: Timeframe code (e.g., "M15", "H1", "H4", "D1")
            
        Returns:
            List of resampled candles
        """
        from resample_5m import resample
        
        with self._lock:
            t_lock_start = time.perf_counter()
            # Check if we have cached resampled data
            cache_key = (symbol.upper(), timeframe.upper())
            
            # Get current 5m candles
            m5_candles = self._cache.get(symbol.upper(), [])
            market_hit = bool(m5_candles)
            if market_hit:
                self._stats["market_hit"] += 1
            else:
                self._stats["market_miss"] += 1

            market_cache_get_ms = (time.perf_counter() - t_lock_start) * 1000.0

            if not m5_candles:
                empty: List[Dict[str, Any]] = []
                meta = {
                    "symbol": symbol.upper(),
                    "timeframe": timeframe.upper(),
                    "market_cache_hit": False,
                    "market_cache_get_ms": market_cache_get_ms,
                    "resample_cache_hit": False,
                    "resample_ms": 0.0,
                }
                return (empty, meta) if with_meta else empty
            
            # Get last timestamp of 5m data
            last_m5_ts = m5_candles[-1]['time'] if m5_candles else None
            
            # Check cache validity
            cached_entry = self._tf_cache.get(cache_key)
            cur_rev = int(self._rev.get(symbol.upper(), 0))
            if (
                cached_entry
                and cached_entry.get("last_ts") == last_m5_ts
                and int(cached_entry.get("rev", -1)) == cur_rev
            ):
                # Cache is valid, return cached data
                self._stats["resample_hit"] += 1
                out = list(cached_entry["candles"])
                meta = {
                    "symbol": symbol.upper(),
                    "timeframe": timeframe.upper(),
                    "market_cache_hit": market_hit,
                    "market_cache_get_ms": market_cache_get_ms,
                    "resample_cache_hit": True,
                    "resample_ms": 0.0,
                    "m5_last_ts": last_m5_ts,
                }
                return (out, meta) if with_meta else out
            
            # Cache miss or invalid - resample
            self._stats["resample_miss"] += 1
            t_resample = time.perf_counter()
            resampled = resample(m5_candles, timeframe)
            resample_ms = (time.perf_counter() - t_resample) * 1000.0
            
            # Update cache
            self._tf_cache[cache_key] = {
                "last_ts": last_m5_ts,
                "rev": cur_rev,
                "candles": resampled,
            }
            
            out = list(resampled)
            meta = {
                "symbol": symbol.upper(),
                "timeframe": timeframe.upper(),
                "market_cache_hit": market_hit,
                "market_cache_get_ms": market_cache_get_ms,
                "resample_cache_hit": False,
                "resample_ms": resample_ms,
                "m5_last_ts": last_m5_ts,
            }
            return (out, meta) if with_meta else out

    def save_json(self, path: str) -> None:
        """Persist the entire cache into a JSON file (best-effort, human readable).

        Note: `time` is serialized as ISO-8601 string.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            payload: Dict[str, List[Dict[str, Any]]] = {}
            for symbol, candles in self._cache.items():
                out: List[Dict[str, Any]] = []
                for c in candles:
                    t = c.get("time")
                    if isinstance(t, datetime):
                        # Prefer UTC ISO format for portability
                        if t.tzinfo is None:
                            t = t.replace(tzinfo=timezone.utc)
                        t_str = t.astimezone(timezone.utc).isoformat()
                    else:
                        t_str = str(t)
                    out.append(
                        {
                            "time": t_str,
                            "open": c.get("open"),
                            "high": c.get("high"),
                            "low": c.get("low"),
                            "close": c.get("close"),
                            "volume": c.get("volume"),
                        }
                    )
                payload[symbol] = out

            atomic_write_text(p, json.dumps(payload, ensure_ascii=False))

    def load_json(self, path: str) -> int:
        """Load cache from a JSON file created by `save_json`.

        Returns number of symbols loaded.
        """
        p = Path(path)
        if not p.exists():
            return 0

        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return 0

        # Handle both old format (flat) and new format ({"version": 1, "symbols": {...}})
        if "symbols" in raw and isinstance(raw.get("symbols"), dict):
            symbols_data = raw["symbols"]
        else:
            symbols_data = raw

        def _parse_time(v: Any) -> Optional[datetime]:
            if isinstance(v, datetime):
                return v
            if not isinstance(v, str):
                return None
            s = v.strip()
            if not s:
                return None
            # Support trailing Z
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        loaded = 0
        for symbol, candles in symbols_data.items():
            if not isinstance(symbol, str) or not isinstance(candles, list):
                continue
            parsed: List[Dict[str, Any]] = []
            for c in candles:
                if not isinstance(c, dict):
                    continue
                t = _parse_time(c.get("time"))
                if t is None:
                    continue
                try:
                    parsed.append(
                        {
                            "time": t,
                            "open": float(c.get("open")),
                            "high": float(c.get("high")),
                            "low": float(c.get("low")),
                            "close": float(c.get("close")),
                            **({"volume": int(c.get("volume"))} if c.get("volume") is not None else {}),
                        }
                    )
                except Exception:
                    continue

            if parsed:
                self.upsert_candles(symbol.upper(), parsed)
                loaded += 1
        return loaded

# Global Singleton Instance
market_cache = MarketDataCache()
