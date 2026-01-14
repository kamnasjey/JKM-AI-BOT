#!/usr/bin/env python3
"""Debug script to check outcome tracker"""
from core.outcome_tracker import get_pending_signals, run_outcome_check
from market_data_cache import MarketDataCache
from datetime import datetime

signals = get_pending_signals()
print(f"Pending signals: {len(signals)}")

if signals:
    sig = signals[0]
    sig_id = sig.get("signal_id", "")[:8]
    symbol = sig.get("symbol")
    entry = sig.get("entry")
    sl = sig.get("sl")
    tp = sig.get("tp")
    created_at = sig.get("created_at")
    direction = sig.get("direction")
    
    print(f"\nSignal: {sig_id}...")
    print(f"Symbol: {symbol}")
    print(f"Direction: {direction}")
    print(f"Entry: {entry}, SL: {sl}, TP: {tp}")
    print(f"Created: {created_at} ({datetime.fromtimestamp(created_at)})")
    
    # Check cache
    cache = MarketDataCache()
    candles = cache.get_candles(symbol)
    print(f"\nCache has {len(candles)} candles for {symbol}")
    
    if candles:
        # Find candles after signal
        candles_after = []
        for c in candles:
            c_ts = c.get("timestamp") or 0
            if isinstance(c_ts, str):
                try:
                    c_ts = int(datetime.fromisoformat(c_ts.replace("Z", "+00:00")).timestamp())
                except:
                    c_ts = 0
            if c_ts > created_at:
                candles_after.append(c)
        
        print(f"Candles AFTER signal: {len(candles_after)}")
        
        if candles_after:
            high_since = max(c.get("high", 0) for c in candles_after)
            low_since = min(c.get("low", float("inf")) for c in candles_after)
            print(f"High since entry: {high_since}")
            print(f"Low since entry: {low_since}")
            
            if direction == "SELL":
                print(f"\nSELL signal check:")
                print(f"  TP hit? {low_since} <= {tp} = {low_since <= tp}")
                print(f"  SL hit? {high_since} >= {sl} = {high_since >= sl}")
            else:
                print(f"\nBUY signal check:")
                print(f"  TP hit? {high_since} >= {tp} = {high_since >= tp}")
                print(f"  SL hit? {low_since} <= {sl} = {low_since <= sl}")
        else:
            print("First candle timestamp:", candles[0].get("timestamp"))
            print("Last candle timestamp:", candles[-1].get("timestamp"))
    
    print("\n--- Running outcome check ---")
    result = run_outcome_check(cache)
    print(f"Result: {result}")
else:
    print("No pending signals found")
