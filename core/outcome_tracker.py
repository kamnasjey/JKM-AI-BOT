"""
SL/TP Hit Tracker Service

Monitors open signals and checks if price has hit SL or TP.
Updates signal outcomes: WIN (TP hit), LOSS (SL hit), PENDING (still open).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

OutcomeType = Literal["WIN", "LOSS", "PENDING", "EXPIRED"]


def _state_dir() -> Path:
    return Path(os.getenv("STATE_DIR") or "state")


def _signals_path() -> Path:
    return _state_dir() / "signals.jsonl"


def _outcomes_path() -> Path:
    return _state_dir() / "signal_outcomes.json"


def load_outcomes() -> Dict[str, Dict[str, Any]]:
    """Load signal outcomes from persistent storage.
    
    Returns: {signal_id: {outcome, hit_price, hit_time, ...}}
    """
    path = _outcomes_path()
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load outcomes: {e}")
    return {}


def save_outcomes(outcomes: Dict[str, Dict[str, Any]]) -> None:
    """Persist signal outcomes."""
    path = _outcomes_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(outcomes, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to save outcomes: {e}")


def get_pending_signals(max_age_hours: int = 72) -> List[Dict[str, Any]]:
    """Get signals that are still PENDING (not yet hit SL/TP).
    
    Args:
        max_age_hours: Only check signals created within this time window
    
    Returns: List of signal dicts with entry/sl/tp/direction
    """
    path = _signals_path()
    if not path.exists():
        return []
    
    outcomes = load_outcomes()
    now_ts = int(time.time())
    cutoff_ts = now_ts - (max_age_hours * 3600)
    
    pending = []
    
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    sig = json.loads(line)
                except Exception:
                    continue
                
                signal_id = sig.get("signal_id")
                if not signal_id:
                    continue
                
                # Skip if already has outcome
                if signal_id in outcomes and outcomes[signal_id].get("outcome") != "PENDING":
                    continue
                
                # Parse timestamp
                ts = sig.get("created_at") or sig.get("ts")
                if isinstance(ts, (int, float)):
                    sig_ts = int(ts)
                elif isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        sig_ts = int(dt.timestamp())
                    except Exception:
                        sig_ts = 0
                else:
                    sig_ts = 0
                
                # Skip old signals
                if sig_ts < cutoff_ts:
                    continue
                
                # Need entry, sl, tp for tracking
                entry = sig.get("entry")
                sl = sig.get("sl")
                tp = sig.get("tp")
                direction = str(sig.get("direction") or "").upper()
                
                if entry and sl and tp and direction in ("BUY", "SELL"):
                    pending.append({
                        "signal_id": signal_id,
                        "symbol": sig.get("symbol"),
                        "tf": sig.get("tf") or sig.get("timeframe"),
                        "direction": direction,
                        "entry": float(entry),
                        "sl": float(sl),
                        "tp": float(tp),
                        "created_at": sig_ts,
                    })
    except Exception as e:
        logger.error(f"Failed to read signals: {e}")
    
    return pending


def check_signal_outcome(
    signal: Dict[str, Any],
    current_price: float,
    high_since_entry: Optional[float] = None,
    low_since_entry: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Check if a signal has hit SL or TP.
    
    Args:
        signal: Signal dict with entry, sl, tp, direction
        current_price: Current market price
        high_since_entry: Highest price since signal was created (for TP check)
        low_since_entry: Lowest price since signal was created (for SL check)
    
    Returns: Outcome dict if resolved, None if still pending
    """
    direction = signal.get("direction")
    entry = signal.get("entry")
    sl = signal.get("sl")
    tp = signal.get("tp")
    
    if not all([direction, entry, sl, tp]):
        return None
    
    # Use high/low if provided, otherwise use current price
    check_high = high_since_entry if high_since_entry is not None else current_price
    check_low = low_since_entry if low_since_entry is not None else current_price
    
    now_ts = int(time.time())
    
    if direction == "BUY":
        # BUY: TP is above entry, SL is below
        if check_high >= tp:
            return {
                "outcome": "WIN",
                "hit_price": tp,
                "hit_time": now_ts,
                "pips_gained": abs(tp - entry),
            }
        if check_low <= sl:
            return {
                "outcome": "LOSS",
                "hit_price": sl,
                "hit_time": now_ts,
                "pips_lost": abs(entry - sl),
            }
    
    elif direction == "SELL":
        # SELL: TP is below entry, SL is above
        if check_low <= tp:
            return {
                "outcome": "WIN",
                "hit_price": tp,
                "hit_time": now_ts,
                "pips_gained": abs(entry - tp),
            }
        if check_high >= sl:
            return {
                "outcome": "LOSS",
                "hit_price": sl,
                "hit_time": now_ts,
                "pips_lost": abs(sl - entry),
            }
    
    return None


def update_signal_outcome(signal_id: str, outcome_data: Dict[str, Any]) -> None:
    """Update outcome for a specific signal."""
    outcomes = load_outcomes()
    outcomes[signal_id] = outcome_data
    save_outcomes(outcomes)
    logger.info(f"Signal {signal_id} outcome: {outcome_data.get('outcome')}")


def get_signal_outcome(signal_id: str) -> Optional[Dict[str, Any]]:
    """Get outcome for a specific signal."""
    outcomes = load_outcomes()
    return outcomes.get(signal_id)


def get_outcome_stats(days: int = 30) -> Dict[str, Any]:
    """Get outcome statistics for recent signals.
    
    Returns: {total, wins, losses, pending, win_rate, ...}
    """
    outcomes = load_outcomes()
    now_ts = int(time.time())
    cutoff_ts = now_ts - (days * 86400)
    
    stats = {
        "total": 0,
        "wins": 0,
        "losses": 0,
        "pending": 0,
        "expired": 0,
        "win_rate": None,
        "total_pips_gained": 0.0,
        "total_pips_lost": 0.0,
        "by_symbol": {},
    }
    
    for sig_id, data in outcomes.items():
        hit_time = data.get("hit_time") or data.get("created_at", 0)
        if hit_time < cutoff_ts:
            continue
        
        stats["total"] += 1
        outcome = data.get("outcome")
        
        if outcome == "WIN":
            stats["wins"] += 1
            stats["total_pips_gained"] += data.get("pips_gained", 0)
        elif outcome == "LOSS":
            stats["losses"] += 1
            stats["total_pips_lost"] += data.get("pips_lost", 0)
        elif outcome == "PENDING":
            stats["pending"] += 1
        elif outcome == "EXPIRED":
            stats["expired"] += 1
        
        # By symbol
        symbol = data.get("symbol", "UNKNOWN")
        if symbol not in stats["by_symbol"]:
            stats["by_symbol"][symbol] = {"wins": 0, "losses": 0, "pending": 0}
        if outcome == "WIN":
            stats["by_symbol"][symbol]["wins"] += 1
        elif outcome == "LOSS":
            stats["by_symbol"][symbol]["losses"] += 1
        elif outcome == "PENDING":
            stats["by_symbol"][symbol]["pending"] += 1
    
    # Calculate win rate
    decided = stats["wins"] + stats["losses"]
    if decided > 0:
        stats["win_rate"] = round(stats["wins"] / decided, 4)
    
    return stats


def run_outcome_check(market_data_cache: Any) -> Dict[str, Any]:
    """Run outcome check for all pending signals.
    
    Args:
        market_data_cache: MarketDataCache instance for getting current prices
    
    Returns: Summary of updates made
    """
    pending = get_pending_signals()
    
    if not pending:
        return {"checked": 0, "updated": 0}
    
    # If cache is empty, try loading from file
    cache_path = os.getenv("MARKET_CACHE_PATH", "state/market_cache.json")
    try:
        if not market_data_cache.get_all_symbols():
            loaded = market_data_cache.load_json(cache_path)
            if loaded:
                logger.info(f"Loaded {loaded} symbols from {cache_path} for outcome check")
    except Exception as e:
        logger.warning(f"Failed to load cache for outcome check: {e}")
    
    outcomes = load_outcomes()
    updated = 0
    
    for sig in pending:
        symbol = sig.get("symbol")
        if not symbol:
            continue
        
        try:
            # Get all candles from cache
            candles = market_data_cache.get_candles(symbol)
            if not candles:
                continue
            
            sig_ts = sig.get("created_at", 0)
            
            # Find candles AFTER signal was created
            candles_after = []
            for c in candles:
                # Handle both "time" (datetime) and "timestamp" (int) formats
                c_time = c.get("time") or c.get("timestamp") or c.get("ts")
                if isinstance(c_time, datetime):
                    c_ts = int(c_time.timestamp())
                elif isinstance(c_time, str):
                    try:
                        c_ts = int(datetime.fromisoformat(c_time.replace("Z", "+00:00")).timestamp())
                    except:
                        c_ts = 0
                elif isinstance(c_time, (int, float)):
                    c_ts = int(c_time)
                else:
                    c_ts = 0
                if c_ts > sig_ts:
                    candles_after.append(c)
            
            if not candles_after:
                # No candles after signal, still pending
                continue
            
            # Find HIGH and LOW since signal entry
            high_since = max(c.get("high", 0) for c in candles_after)
            low_since = min(c.get("low", float("inf")) for c in candles_after)
            current_price = candles_after[-1].get("close")
            
            if current_price is None:
                continue
            
            # Check outcome using high/low since entry
            result = check_signal_outcome(
                sig,
                current_price,
                high_since_entry=high_since,
                low_since_entry=low_since,
            )
            
            if result:
                signal_id = sig["signal_id"]
                result["symbol"] = symbol
                result["direction"] = sig.get("direction")
                result["entry"] = sig.get("entry")
                result["sl"] = sig.get("sl")
                result["tp"] = sig.get("tp")
                result["created_at"] = sig.get("created_at")
                result["candles_checked"] = len(candles_after)
                result["high_since"] = high_since
                result["low_since"] = low_since
                
                outcomes[signal_id] = result
                updated += 1
                logger.info(f"Signal {signal_id} hit {result['outcome']} at {result['hit_price']} (high={high_since}, low={low_since})")
        
        except Exception as e:
            logger.warning(f"Failed to check outcome for {sig.get('signal_id')}: {e}")
    
    if updated > 0:
        save_outcomes(outcomes)
    
    return {"checked": len(pending), "updated": updated}


# Background job function for APScheduler
def outcome_check_job(market_data_cache: Any) -> None:
    """Background job to periodically check signal outcomes."""
    try:
        result = run_outcome_check(market_data_cache)
        if result["updated"] > 0:
            logger.info(f"Outcome check: {result['checked']} checked, {result['updated']} updated")
    except Exception as e:
        logger.error(f"Outcome check job failed: {e}")
