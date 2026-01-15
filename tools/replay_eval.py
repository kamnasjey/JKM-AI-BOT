#!/usr/bin/env python
"""
replay_eval.py
--------------
Replay evaluation tool for detector development.

Replays historical candle data through detectors and collects metrics:
- Total hits / no-hits per detector
- Hit rate and win/loss analysis
- Evidence breakdown

Usage:
    python tools/replay_eval.py --symbol BTCUSD --tf 15m --days 7
    python tools/replay_eval.py --fixture smoke --detectors pinbar,engulfing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_blocks import Candle
from core.primitives import PrimitiveResults
from engines.detectors.base import DetectorResult
from engines.detectors.registry import DetectorRegistry
from engines.detectors.runner import safe_detect


@dataclass
class DetectorStats:
    """Statistics for a single detector."""
    detector_name: str
    total_bars: int = 0
    hits: int = 0
    no_hits: int = 0
    errors: int = 0
    
    buy_hits: int = 0
    sell_hits: int = 0
    
    avg_confidence: float = 0.0
    avg_rr: float = 0.0
    
    sample_evidence: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def hit_rate(self) -> float:
        if self.total_bars == 0:
            return 0.0
        return self.hits / self.total_bars
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "detector_name": self.detector_name,
            "total_bars": self.total_bars,
            "hits": self.hits,
            "no_hits": self.no_hits,
            "errors": self.errors,
            "hit_rate": round(self.hit_rate, 4),
            "buy_hits": self.buy_hits,
            "sell_hits": self.sell_hits,
            "avg_confidence": round(self.avg_confidence, 3),
            "avg_rr": round(self.avg_rr, 2),
            "sample_evidence": self.sample_evidence[:3],  # Limit samples
        }


@dataclass
class ReplayResult:
    """Complete replay evaluation result."""
    symbol: str
    timeframe: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_bars: int = 0
    
    detector_stats: Dict[str, DetectorStats] = field(default_factory=dict)
    
    elapsed_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_bars": self.total_bars,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "detectors": {
                name: stats.to_dict()
                for name, stats in self.detector_stats.items()
            },
        }


def load_candles_from_fixture(fixture_id: str) -> List[Candle]:
    """Load candles from a test fixture."""
    from tests.fixtures.candles.fixtures import load_candles
    return load_candles(fixture_id)


def load_candles_from_cache(
    symbol: str,
    timeframe: str,
    days: int = 7,
) -> List[Candle]:
    """Load candles from market data cache."""
    try:
        from market_data_cache import MarketDataCache
        cache = MarketDataCache()
        candles = cache.get_candles(symbol, timeframe)
        if candles:
            # Filter to recent days
            cutoff = datetime.utcnow() - timedelta(days=days)
            candles = [c for c in candles if c.time >= cutoff]
        return candles or []
    except Exception as e:
        print(f"Failed to load from cache: {e}")
        return []


def create_primitives(candles: List[Candle]) -> PrimitiveResults:
    """Create primitive results from candles."""
    try:
        from core.primitives import build_primitives
        return build_primitives(candles)
    except ImportError:
        # Fallback: minimal primitives
        return PrimitiveResults(
            swing_highs=[],
            swing_lows=[],
            sr_levels=[],
            range_box=None,
            fibo_levels=[],
        )


def run_replay(
    candles: List[Candle],
    detector_names: Optional[List[str]] = None,
    min_window: int = 30,
) -> ReplayResult:
    """Run replay evaluation on candles.
    
    Args:
        candles: List of candles to evaluate
        detector_names: Optional list of detector names to test (default: all)
        min_window: Minimum candles before starting evaluation
    
    Returns:
        ReplayResult with per-detector statistics
    """
    import time
    t0 = time.perf_counter()
    
    result = ReplayResult(
        symbol="REPLAY",
        timeframe="N/A",
        total_bars=len(candles),
        start_time=candles[0].time if candles else None,
        end_time=candles[-1].time if candles else None,
    )
    
    if len(candles) < min_window:
        result.elapsed_seconds = time.perf_counter() - t0
        return result
    
    # Get detectors
    registry = DetectorRegistry()
    all_detectors = registry.list_detectors()
    
    if detector_names:
        detector_names = [d.strip() for d in detector_names if d.strip()]
    else:
        detector_names = all_detectors
    
    # Initialize stats
    for name in detector_names:
        result.detector_stats[name] = DetectorStats(detector_name=name)
    
    # Create detectors
    detectors = {}
    for name in detector_names:
        try:
            det = registry.create_detector(name)
            if det:
                detectors[name] = det
        except Exception as e:
            print(f"Failed to create detector {name}: {e}")
    
    # Sliding window replay
    for i in range(min_window, len(candles)):
        window = candles[:i + 1]
        primitives = create_primitives(window)
        
        for name, det in detectors.items():
            stats = result.detector_stats[name]
            stats.total_bars += 1
            
            try:
                det_result, error = safe_detect(
                    det,
                    candles=window,
                    primitives=primitives,
                    context={},
                )
                
                if error:
                    stats.errors += 1
                    continue
                
                if det_result.match:
                    stats.hits += 1
                    
                    if det_result.direction == "BUY":
                        stats.buy_hits += 1
                    elif det_result.direction == "SELL":
                        stats.sell_hits += 1
                    
                    # Update averages
                    if det_result.confidence:
                        n = stats.hits
                        stats.avg_confidence = (
                            (stats.avg_confidence * (n - 1) + det_result.confidence) / n
                        )
                    
                    if det_result.rr and det_result.rr > 0:
                        rr_count = stats.buy_hits + stats.sell_hits
                        if rr_count > 0:
                            stats.avg_rr = (
                                (stats.avg_rr * (rr_count - 1) + det_result.rr) / rr_count
                            )
                    
                    # Sample evidence
                    if len(stats.sample_evidence) < 5:
                        stats.sample_evidence.append({
                            "bar_index": i,
                            "direction": det_result.direction,
                            "confidence": det_result.confidence,
                            "reason_codes": det_result.reason_codes[:3],
                        })
                else:
                    stats.no_hits += 1
                    
            except Exception as e:
                stats.errors += 1
    
    result.elapsed_seconds = time.perf_counter() - t0
    return result


def print_summary(result: ReplayResult) -> None:
    """Print human-readable summary."""
    print(f"\n{'='*60}")
    print(f"REPLAY EVALUATION SUMMARY")
    print(f"{'='*60}")
    print(f"Symbol: {result.symbol}")
    print(f"Timeframe: {result.timeframe}")
    print(f"Total Bars: {result.total_bars}")
    print(f"Time Range: {result.start_time} to {result.end_time}")
    print(f"Elapsed: {result.elapsed_seconds:.2f}s")
    print(f"\n{'='*60}")
    print(f"{'Detector':<30} {'Hits':<8} {'Rate':<8} {'BUY':<6} {'SELL':<6} {'Conf':<6} {'RR':<6}")
    print(f"{'-'*60}")
    
    for name, stats in sorted(result.detector_stats.items()):
        print(
            f"{name:<30} "
            f"{stats.hits:<8} "
            f"{stats.hit_rate*100:>5.1f}%  "
            f"{stats.buy_hits:<6} "
            f"{stats.sell_hits:<6} "
            f"{stats.avg_confidence:>5.2f} "
            f"{stats.avg_rr:>5.1f}"
        )
    
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Replay evaluation for detectors")
    parser.add_argument("--fixture", type=str, help="Fixture ID to use")
    parser.add_argument("--symbol", type=str, default="BTCUSD", help="Symbol for cache lookup")
    parser.add_argument("--tf", type=str, default="15m", help="Timeframe")
    parser.add_argument("--days", type=int, default=7, help="Days of history")
    parser.add_argument("--detectors", type=str, help="Comma-separated detector names")
    parser.add_argument("--min-window", type=int, default=30, help="Min bars before eval")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--output", type=str, help="Output file path")
    
    args = parser.parse_args()
    
    # Load candles
    if args.fixture:
        candles = load_candles_from_fixture(args.fixture)
        symbol = f"FIXTURE:{args.fixture}"
        tf = "fixture"
    else:
        candles = load_candles_from_cache(args.symbol, args.tf, args.days)
        symbol = args.symbol
        tf = args.tf
    
    if not candles:
        print(f"No candles loaded for {symbol}")
        sys.exit(1)
    
    print(f"Loaded {len(candles)} candles for {symbol}")
    
    # Parse detectors
    detector_names = None
    if args.detectors:
        detector_names = [d.strip() for d in args.detectors.split(",")]
    
    # Run replay
    result = run_replay(
        candles,
        detector_names=detector_names,
        min_window=args.min_window,
    )
    result.symbol = symbol
    result.timeframe = tf
    
    # Output
    if args.json or args.output:
        output_data = json.dumps(result.to_dict(), indent=2, default=str)
        if args.output:
            Path(args.output).write_text(output_data)
            print(f"Results written to {args.output}")
        else:
            print(output_data)
    else:
        print_summary(result)


if __name__ == "__main__":
    main()
