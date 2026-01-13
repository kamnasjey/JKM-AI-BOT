#!/usr/bin/env python3
from pathlib import Path
from market_data_cache import MarketDataCache

cache_path = Path("state/market_cache.json")
temp_cache = MarketDataCache(max_len=20000)
loaded = temp_cache.load_json(str(cache_path))
print(f"Loaded {loaded} symbols")

for sym in temp_cache.get_all_symbols():
    candles = temp_cache.get_candles(sym)
    print(f"{sym}: {len(candles)} candles")
    if candles:
        first_time = candles[0].get("time")
        last_time = candles[-1].get("time")
        print(f"  First: {first_time}")
        print(f"  Last: {last_time}")
