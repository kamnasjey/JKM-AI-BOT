#!/usr/bin/env python3
"""Debug simulation backtest step by step"""
from pathlib import Path
from market_data_cache import MarketDataCache
from datetime import datetime, timezone, timedelta

# Load cache
cache_path = Path("state/market_cache.json")
temp_cache = MarketDataCache(max_len=20000)
temp_cache.load_json(str(cache_path))

# Get candles for a symbol
symbol = "XAUUSD"
m5_candles = temp_cache.get_candles(symbol)
print(f"M5 candles for {symbol}: {len(m5_candles)}")

# Resample to M15
def _resample_candles(candles, factor):
    if not candles or factor < 1:
        return []
    result = []
    for i in range(0, len(candles) - factor + 1, factor):
        group = candles[i:i + factor]
        if len(group) < factor:
            break
        resampled = {
            "time": group[0].get("time"),
            "open": group[0].get("open"),
            "high": max(c.get("high", 0) for c in group),
            "low": min(c.get("low", float("inf")) for c in group),
            "close": group[-1].get("close"),
            "volume": sum(c.get("volume", 0) for c in group),
        }
        result.append(resampled)
    return result

m15_candles = _resample_candles(m5_candles, 3)
print(f"M15 candles: {len(m15_candles)}")

# Load detectors
from detectors.registry import DETECTOR_REGISTRY
print(f"Available detectors: {list(DETECTOR_REGISTRY.keys())}")

# Try to run one detector
detector_name = "trend_fibo"
if detector_name in DETECTOR_REGISTRY:
    detector_fn = DETECTOR_REGISTRY[detector_name]
    
    # Simulate running on a few candles
    for i in range(50, min(55, len(m15_candles))):
        current_candles = m15_candles[:i+1]
        current_candle = current_candles[-1]
        
        ctx = {
            "symbol": symbol,
            "tf": "M15",
            "candles": current_candles,
            "current_price": current_candle.get("close"),
        }
        
        try:
            result = detector_fn(ctx)
            if result:
                print(f"Bar {i}: {result}")
        except Exception as e:
            print(f"Bar {i} Error: {e}")
else:
    print(f"Detector {detector_name} not found")
