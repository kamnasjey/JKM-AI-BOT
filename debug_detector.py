#!/usr/bin/env python3
"""Debug detector invocation in simulation backtest"""
from pathlib import Path
from market_data_cache import MarketDataCache
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import List, Optional

# Load cache
cache_path = Path("state/market_cache.json")
temp_cache = MarketDataCache(max_len=20000)
temp_cache.load_json(str(cache_path))

# Get and resample candles
symbol = "XAUUSD"
m5_candles = temp_cache.get_candles(symbol)

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
            "volume": sum(c.get("volume") or 0 for c in group),
        }
        result.append(resampled)
    return result

m15_candles = _resample_candles(m5_candles, 3)
h4_candles = _resample_candles(m15_candles, 16)
print(f"M15 candles: {len(m15_candles)}")
print(f"H4 candles: {len(h4_candles)}")

# Create primitives
@dataclass
class MinimalPrimitives:
    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    trend_direction: str = "flat"

# Load detector
from detectors.registry import DETECTOR_REGISTRY
from detectors.base import DetectorConfig

detector_name = "break_retest"
detector_class = DETECTOR_REGISTRY[detector_name]
detector_instance = detector_class(config=DetectorConfig(enabled=True))

print(f"Detector: {detector_name}")
print(f"Detector params_schema: {detector_instance.get_params_schema()}")

# Try running on different candle indices
signals_found = 0
for i in range(50, min(200, len(m15_candles) - 20)):
    current_candles = m15_candles[:i+1]
    current_candle = current_candles[-1]
    
    h4_index = min(i // 16, len(h4_candles) - 1)
    current_h4_candles = h4_candles[:h4_index+1] if h4_index > 0 else h4_candles[:1]
    
    if len(current_candles) > 20:
        recent = current_candles[-20:]
        highs = [c.get("high", 0) for c in recent]
        lows = [c.get("low", float("inf")) for c in recent]
        primitives = MinimalPrimitives(
            swing_high=max(highs),
            swing_low=min(lows),
            support_levels=[min(lows)],
            resistance_levels=[max(highs)],
        )
    else:
        primitives = MinimalPrimitives()
    
    user_config = {
        "min_rr": 2.0,
        "trend_tf": "H4",
        "entry_tf": "M15",
    }
    
    try:
        result = detector_instance.detect(
            pair=symbol,
            entry_candles=current_candles,
            trend_candles=current_h4_candles,
            primitives=primitives,
            user_config=user_config,
        )
        if result:
            signals_found += 1
            print(f"Bar {i}: SIGNAL! {result.direction} entry={result.entry} sl={result.sl} tp={result.tp} rr={result.rr}")
            if signals_found >= 3:
                break
    except Exception as e:
        print(f"Bar {i} error: {type(e).__name__}: {e}")
        break

print(f"\nTotal signals found: {signals_found}")
