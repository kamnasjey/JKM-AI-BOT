# market_data_cache.py
import threading
import time
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime, timezone
import json
from pathlib import Path
import json
import os

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

        with self._lock:
            sym = symbol.upper()
            current = self._cache.get(sym, [])
            prev_last_ts = current[-1]["time"] if current else None
            
            # Create a dict for easy lookup/update by time
            # Assuming 'time' is datetime object
            data_map = {c['time']: c for c in current}
            
            for c in candles:
                # Ensure time is present
                if 'time' not in c:
                    continue
                data_map[c['time']] = c
                
            # Convert back to list and sort
            merged = sorted(data_map.values(), key=lambda x: x['time'])
            
            # Trim to max_len
            if len(merged) > self._max_len:
                merged = merged[-self._max_len:]
                
            self._cache[sym] = merged

            # Invalidate resampled cache ONLY if we appended newer data.
            # (Spec requirement: invalidate per symbol whenever upsert adds newer last timestamp.)
            new_last_ts = merged[-1]["time"] if merged else None
            if prev_last_ts is None:
                self._invalidate_tf_cache(sym)
            elif new_last_ts is not None and new_last_ts > prev_last_ts:
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
            if cached_entry and cached_entry.get('last_ts') == last_m5_ts:
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
                'last_ts': last_m5_ts,
                'candles': resampled,
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
        for symbol, candles in raw.items():
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

    def save_json(self, path: str) -> None:
        """Persist the entire cache to a JSON file.

        Times are stored as ISO8601 strings.
        """
        with self._lock:
            payload: Dict[str, Any] = {
                "version": 1,
                "symbols": {},
            }
            for sym, candles in self._cache.items():
                out: List[Dict[str, Any]] = []
                for c in candles:
                    t = c.get("time")
                    if isinstance(t, datetime):
                        t_str = t.astimezone(timezone.utc).isoformat()
                    else:
                        t_str = str(t)
                    out.append({
                        "time": t_str,
                        "open": c.get("open"),
                        "high": c.get("high"),
                        "low": c.get("low"),
                        "close": c.get("close"),
                        "volume": c.get("volume"),
                    })
                payload["symbols"][sym] = out

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)

    def load_json(self, path: str) -> None:
        """Load cache from a JSON file created by save_json()."""
        if not os.path.exists(path):
            return

        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        if not isinstance(symbols, dict):
            return

        loaded: Dict[str, List[Dict[str, Any]]] = {}
        for sym, items in symbols.items():
            if not isinstance(sym, str) or not isinstance(items, list):
                continue
            candles: List[Dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                t_raw = item.get("time")
                try:
                    if isinstance(t_raw, str):
                        # fromisoformat supports offsets; ensure tz-aware
                        t = datetime.fromisoformat(t_raw)
                        if t.tzinfo is None:
                            t = t.replace(tzinfo=timezone.utc)
                        else:
                            t = t.astimezone(timezone.utc)
                    else:
                        continue
                except Exception:
                    continue
                try:
                    candles.append({
                        "time": t,
                        "open": float(item.get("open")),
                        "high": float(item.get("high")),
                        "low": float(item.get("low")),
                        "close": float(item.get("close")),
                        **({"volume": float(item.get("volume"))} if item.get("volume") is not None else {}),
                    })
                except Exception:
                    continue

            candles = sorted(candles, key=lambda x: x["time"])
            if len(candles) > self._max_len:
                candles = candles[-self._max_len:]
            loaded[sym.upper()] = candles

        with self._lock:
            self._cache = loaded

# Global Singleton Instance
market_cache = MarketDataCache()
