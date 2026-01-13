#!/usr/bin/env python3
"""Debug specific detector with detailed output"""
from pathlib import Path
from market_data_cache import MarketDataCache
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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

# Import primitives
from core.primitives import (
    PrimitiveResults, SwingResult, SRZoneResult, 
    TrendStructureResult, FibLevelResult
)
from engine_blocks import Swing

# Load detector
from detectors.registry import DETECTOR_REGISTRY
from detectors.base import DetectorConfig

# Try all detectors with debug
for detector_name in ["trend_fibo", "break_retest", "pinbar_at_level"]:
    detector_class = DETECTOR_REGISTRY.get(detector_name)
    if not detector_class:
        print(f"Detector {detector_name} not found")
        continue
    
    detector_instance = detector_class(config=DetectorConfig(enabled=True))
    print(f"\n=== Testing {detector_name} ===")
    
    signals_found = 0
    for i in range(50, min(200, len(m15_candles) - 20)):
        current_candles = m15_candles[:i+1]
        current_candle = current_candles[-1]
        
        h4_index = min(i // 16, len(h4_candles) - 1)
        current_h4_candles = h4_candles[:h4_index+1] if h4_index > 0 else h4_candles[:1]
        
        if len(current_candles) > 30:
            recent = current_candles[-30:]
            highs = [c.get("high", 0) for c in recent]
            lows = [c.get("low", float("inf")) for c in recent]
            closes = [c.get("close", 0) for c in recent]
            
            swing_high = max(highs)
            swing_low = min(lows)
            last_close = closes[-1]
            
            swing = Swing(low=swing_low, high=swing_high)
            
            if closes[-1] > closes[0]:
                trend_dir = "up"
            elif closes[-1] < closes[0]:
                trend_dir = "down"
            else:
                trend_dir = "flat"
            
            primitives = PrimitiveResults(
                swing=SwingResult(swing=swing, direction=trend_dir, found=True),
                sr_zones=SRZoneResult(
                    support=swing_low,
                    resistance=swing_high,
                    last_close=last_close,
                    zones=[(swing_low, swing_high)],
                ),
                trend_structure=TrendStructureResult(
                    direction=trend_dir,
                    structure_valid=True,
                ),
                fib_levels=FibLevelResult(
                    retrace={0.382: swing_low + (swing_high - swing_low) * 0.382,
                            0.5: swing_low + (swing_high - swing_low) * 0.5,
                            0.618: swing_low + (swing_high - swing_low) * 0.618},
                    extensions={1.618: swing_high + (swing_high - swing_low) * 0.618},
                    swing=swing,
                ),
            )
            
            user_config = {
                "min_rr": 1.0,
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
                    print(f"  Bar {i}: SIGNAL {result.direction} entry={result.entry:.2f} sl={result.sl:.2f} tp={result.tp:.2f}")
                    if signals_found >= 2:
                        break
            except Exception as e:
                if i == 50:  # Only print first error
                    print(f"  Bar {i} error: {type(e).__name__}: {e}")
                break
    
    print(f"  Total signals: {signals_found}")
