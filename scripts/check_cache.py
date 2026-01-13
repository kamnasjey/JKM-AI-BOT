#!/usr/bin/env python3
"""Check market cache data range"""
import json
with open("/app/state/market_cache.json") as f:
    d = json.load(f)

symbols = d.get("symbols", d)  # Handle both formats
print(f"Total symbols: {len(symbols)}")
for sym in list(symbols.keys())[:5]:
    candles = symbols[sym]
    if isinstance(candles, list) and candles:
        first = candles[0].get("time") or candles[0].get("timestamp")
        last = candles[-1].get("time") or candles[-1].get("timestamp")
        print(f"{sym}: {len(candles)} candles, first={first}, last={last}")
    else:
        print(f"{sym}: 0 candles")
