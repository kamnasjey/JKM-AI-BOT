#!/usr/bin/env python3
"""Test outcome check with loaded cache"""
from core.outcome_tracker import run_outcome_check, get_pending_signals
from market_data_cache import market_cache
from datetime import datetime

# Check cache
all_symbols = market_cache.get_all_symbols()
print(f"Cache symbols: {len(all_symbols)}")

# Check EURAUD
euraud = market_cache.get_candles("EURAUD")
print(f"EURAUD candles in RAM: {len(euraud)}")

if euraud:
    first_time = euraud[0].get("time")
    last_time = euraud[-1].get("time")
    print(f"First: {first_time}")
    print(f"Last: {last_time}")
    
    # Check pending signals
    pending = get_pending_signals()
    print(f"\nPending signals: {len(pending)}")
    
    if pending:
        sig = pending[0]
        created_at = sig.get("created_at")
        print(f"First signal created at: {datetime.fromtimestamp(created_at)}")
        
        # Count candles after signal
        candles_after = []
        for c in euraud:
            c_time = c.get("time")
            if isinstance(c_time, datetime):
                c_ts = c_time.timestamp()
            else:
                c_ts = 0
            if c_ts > created_at:
                candles_after.append(c)
        
        print(f"Candles after signal: {len(candles_after)}")
        
        if candles_after:
            high_since = max(c.get("high", 0) for c in candles_after)
            low_since = min(c.get("low", float("inf")) for c in candles_after)
            print(f"High since: {high_since}")
            print(f"Low since: {low_since}")
            print(f"SL: {sig.get('sl')}, TP: {sig.get('tp')}")

# Run outcome check
print("\n--- Running outcome check ---")
result = run_outcome_check(market_cache)
print(f"Result: {result}")
