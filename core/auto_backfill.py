# core/auto_backfill.py
"""
Auto-Backfill Module
====================
Automatically detects and fills data gaps in market data cache.

Environment Variables:
- AUTO_BACKFILL_ENABLED: "1" to enable (default: "1")
- AUTO_BACKFILL_MAX_GAP_HOURS: Max gap size to backfill (default: 168 = 7 days)
- AUTO_BACKFILL_MIN_GAP_MINUTES: Minimum gap to trigger backfill (default: 15 = 3 candles)
- AUTO_BACKFILL_BATCH_SIZE: Max candles per API request (default: 500)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def is_backfill_enabled() -> bool:
    """Check if auto-backfill is enabled via environment variable."""
    val = os.getenv("AUTO_BACKFILL_ENABLED", "1").strip().lower()
    return val in ("1", "true", "yes", "on")


def get_backfill_config() -> Dict[str, Any]:
    """Get backfill configuration from environment."""
    return {
        "enabled": is_backfill_enabled(),
        "max_gap_hours": int(os.getenv("AUTO_BACKFILL_MAX_GAP_HOURS", "168")),  # 7 days
        "min_gap_minutes": int(os.getenv("AUTO_BACKFILL_MIN_GAP_MINUTES", "15")),  # 3 candles
        "batch_size": int(os.getenv("AUTO_BACKFILL_BATCH_SIZE", "500")),
    }


def detect_gaps(
    candles: List[Dict[str, Any]],
    expected_interval_minutes: int = 5,
    min_gap_minutes: int = 15,
) -> List[Dict[str, Any]]:
    """
    Detect gaps in candle data.
    
    Args:
        candles: List of candles sorted by time ascending
        expected_interval_minutes: Expected interval between candles (5 for M5)
        min_gap_minutes: Minimum gap size to report (default 15 = 3 missing candles)
    
    Returns:
        List of gap info dicts: [{"start": datetime, "end": datetime, "missing_candles": int}, ...]
    """
    if not candles or len(candles) < 2:
        return []
    
    gaps: List[Dict[str, Any]] = []
    expected_delta = timedelta(minutes=expected_interval_minutes)
    min_gap_delta = timedelta(minutes=min_gap_minutes)
    
    for i in range(1, len(candles)):
        prev_time = candles[i - 1].get("time")
        curr_time = candles[i].get("time")
        
        if not isinstance(prev_time, datetime) or not isinstance(curr_time, datetime):
            continue
        
        actual_delta = curr_time - prev_time
        
        # If gap is larger than minimum threshold
        if actual_delta > min_gap_delta:
            # Calculate how many candles are missing
            missing_candles = int(actual_delta.total_seconds() / (expected_interval_minutes * 60)) - 1
            
            if missing_candles > 0:
                gaps.append({
                    "start": prev_time,
                    "end": curr_time,
                    "gap_minutes": actual_delta.total_seconds() / 60,
                    "missing_candles": missing_candles,
                })
    
    return gaps


def detect_tail_gap(
    candles: List[Dict[str, Any]],
    min_gap_minutes: int = 15,
) -> Optional[Dict[str, Any]]:
    """
    Detect if there's a gap between the last candle and current time.
    
    Returns:
        Gap info dict if gap exists, None otherwise
    """
    if not candles:
        return None
    
    last_candle = candles[-1]
    last_time = last_candle.get("time")
    
    if not isinstance(last_time, datetime):
        return None
    
    now = datetime.now(timezone.utc)
    gap_delta = now - last_time
    gap_minutes = gap_delta.total_seconds() / 60
    
    # Account for the fact that current candle might not be closed yet
    # So we subtract 5 minutes (one candle period)
    effective_gap = gap_minutes - 5
    
    if effective_gap > min_gap_minutes:
        missing_candles = int(effective_gap / 5)
        return {
            "start": last_time,
            "end": now,
            "gap_minutes": gap_minutes,
            "missing_candles": missing_candles,
            "is_tail_gap": True,
        }
    
    return None


def calculate_backfill_params(
    gap: Dict[str, Any],
    batch_size: int = 500,
) -> Dict[str, Any]:
    """
    Calculate parameters for backfill API request.
    
    Returns:
        Dict with since_ts, until_ts, limit for API call
    """
    start = gap["start"]
    end = gap["end"]
    missing = gap["missing_candles"]
    
    # Add small buffer on both sides
    since_ts = start - timedelta(minutes=5)
    until_ts = end + timedelta(minutes=5) if not gap.get("is_tail_gap") else datetime.now(timezone.utc)
    
    # Limit to batch size
    limit = min(missing + 10, batch_size)  # +10 buffer for overlap
    
    return {
        "since_ts": since_ts,
        "until_ts": until_ts,
        "limit": limit,
        "gap_info": gap,
    }


class AutoBackfiller:
    """
    Auto-backfill service that detects and fills gaps in market data.
    
    NOTE: Only works with MASSIVE provider. Simulation/fake data will NOT be backfilled.
    """
    
    def __init__(
        self,
        provider: Any,
        cache: Any,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.provider = provider
        self.cache = cache
        self.config = config or get_backfill_config()
        self._backfill_history: Dict[str, List[Dict[str, Any]]] = {}
        
        # Check if provider is MASSIVE (real data)
        self._is_real_provider = self._check_real_provider()
        if not self._is_real_provider:
            logger.warning(
                "AUTO_BACKFILL | status=disabled | reason=simulation_provider | "
                "message=Backfill only works with MASSIVE API, not simulation data"
            )
    
    def _check_real_provider(self) -> bool:
        """Check if provider is a real data provider (MASSIVE), not simulation."""
        provider_name = str(getattr(self.provider, "name", "")).upper()
        provider_class = type(self.provider).__name__.upper()
        
        # Check for simulation/fake providers
        simulation_indicators = [
            "SIMULATION", "FAKE", "MOCK", "TEST", "DUMMY", "FALLBACK"
        ]
        
        for indicator in simulation_indicators:
            if indicator in provider_name or indicator in provider_class:
                return False
        
        # Must be MASSIVE provider
        if "MASSIVE" in provider_name or "MASSIVE" in provider_class:
            return True
        
        # Check if MASSIVE_API_KEY is configured
        import os
        massive_key = (os.getenv("MASSIVE_API_KEY") or "").strip()
        if not massive_key:
            return False
        
        return True
    
    def check_and_backfill(self, symbol: str) -> Dict[str, Any]:
        """
        Check for gaps in symbol data and attempt to backfill.
        
        NOTE: Will skip backfill if not using MASSIVE API (real data).
        
        Returns:
            Result dict with status and details
        """
        if not self.config.get("enabled", True):
            return {"status": "disabled", "symbol": symbol}
        
        # Skip backfill for simulation/fake data
        if not self._is_real_provider:
            return {
                "status": "skipped",
                "symbol": symbol,
                "reason": "simulation_provider",
                "message": "Backfill only works with MASSIVE API, not simulation data",
            }
        
        candles = self.cache.get_candles(symbol)
        if not candles:
            return {"status": "no_data", "symbol": symbol}
        
        result = {
            "symbol": symbol,
            "status": "ok",
            "gaps_found": 0,
            "gaps_filled": 0,
            "candles_added": 0,
            "gaps": [],
        }
        
        # Detect internal gaps
        gaps = detect_gaps(
            candles,
            min_gap_minutes=self.config.get("min_gap_minutes", 15),
        )
        
        # Detect tail gap (gap between last candle and now)
        tail_gap = detect_tail_gap(
            candles,
            min_gap_minutes=self.config.get("min_gap_minutes", 15),
        )
        if tail_gap:
            gaps.append(tail_gap)
        
        result["gaps_found"] = len(gaps)
        
        # Filter out gaps that are too large
        max_gap_hours = self.config.get("max_gap_hours", 168)
        max_gap_minutes = max_gap_hours * 60
        
        for gap in gaps:
            if gap["gap_minutes"] > max_gap_minutes:
                logger.warning(
                    f"BACKFILL_SKIP | symbol={symbol} | reason=gap_too_large | "
                    f"gap_hours={gap['gap_minutes']/60:.1f}"
                )
                result["gaps"].append({**gap, "action": "skipped", "reason": "too_large"})
                continue
            
            # Attempt to backfill
            try:
                filled = self._fill_gap(symbol, gap)
                result["gaps_filled"] += 1
                result["candles_added"] += filled
                result["gaps"].append({**gap, "action": "filled", "candles_added": filled})
            except Exception as e:
                logger.error(f"BACKFILL_ERROR | symbol={symbol} | error={e}")
                result["gaps"].append({**gap, "action": "error", "error": str(e)})
        
        if result["gaps_filled"] > 0:
            result["status"] = "backfilled"
            logger.info(
                f"BACKFILL_COMPLETE | symbol={symbol} | gaps_filled={result['gaps_filled']} | "
                f"candles_added={result['candles_added']}"
            )
        
        return result
    
    def _fill_gap(self, symbol: str, gap: Dict[str, Any]) -> int:
        """
        Fill a single gap by fetching data from provider.
        
        Returns:
            Number of candles added
        """
        from data_providers.models import Candle, candles_to_cache_dicts
        
        params = calculate_backfill_params(
            gap,
            batch_size=self.config.get("batch_size", 500),
        )
        
        logger.info(
            f"BACKFILL_FETCH | symbol={symbol} | since={params['since_ts']} | "
            f"until={params['until_ts']} | limit={params['limit']}"
        )
        
        # Fetch candles from provider
        if hasattr(self.provider, "fetch_candles"):
            candles = self.provider.fetch_candles(
                symbol,
                timeframe="m5",
                max_count=params["limit"],
                limit=params["limit"],
                since_ts=params["since_ts"],
                until_ts=params["until_ts"],
            )
        elif hasattr(self.provider, "get_candles"):
            candles = self.provider.get_candles(
                symbol,
                timeframe="m5",
                limit=params["limit"],
                since_ts=params["since_ts"],
            )
        else:
            raise ValueError("Provider has no fetch_candles or get_candles method")
        
        if not candles:
            logger.warning(f"BACKFILL_EMPTY | symbol={symbol} | no candles returned")
            return 0
        
        # Convert to cache format and upsert
        if isinstance(candles[0], Candle):
            cache_candles = candles_to_cache_dicts(candles)
        else:
            cache_candles = candles
        
        # Get count before upsert
        before_count = len(self.cache.get_candles(symbol))
        
        # Upsert to cache
        self.cache.upsert_candles(symbol, cache_candles)
        
        # Get count after upsert
        after_count = len(self.cache.get_candles(symbol))
        added = after_count - before_count
        
        # Record in history
        if symbol not in self._backfill_history:
            self._backfill_history[symbol] = []
        self._backfill_history[symbol].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gap": gap,
            "candles_added": added,
        })
        
        return added
    
    def get_backfill_stats(self) -> Dict[str, Any]:
        """Get statistics about backfill operations."""
        stats = {
            "config": self.config,
            "history": {},
        }
        
        for symbol, history in self._backfill_history.items():
            stats["history"][symbol] = {
                "total_backfills": len(history),
                "total_candles_added": sum(h["candles_added"] for h in history),
                "last_backfill": history[-1]["timestamp"] if history else None,
            }
        
        return stats


# Singleton instance for easy access
_backfiller: Optional[AutoBackfiller] = None


def get_backfiller(
    provider: Any = None,
    cache: Any = None,
) -> Optional[AutoBackfiller]:
    """Get or create singleton backfiller instance."""
    global _backfiller
    
    if _backfiller is None and provider is not None and cache is not None:
        _backfiller = AutoBackfiller(provider, cache)
    
    return _backfiller


def run_backfill_check(symbols: List[str]) -> Dict[str, Any]:
    """
    Run backfill check for multiple symbols.
    
    Returns:
        Aggregate results dict
    """
    backfiller = get_backfiller()
    if backfiller is None:
        return {"status": "not_initialized", "symbols": symbols}
    
    results = {
        "status": "ok",
        "total_gaps_found": 0,
        "total_gaps_filled": 0,
        "total_candles_added": 0,
        "symbols": {},
    }
    
    for symbol in symbols:
        result = backfiller.check_and_backfill(symbol)
        results["symbols"][symbol] = result
        results["total_gaps_found"] += result.get("gaps_found", 0)
        results["total_gaps_filled"] += result.get("gaps_filled", 0)
        results["total_candles_added"] += result.get("candles_added", 0)
    
    return results
