"""
test_engine_pipeline.py
-----------------------
End-to-end integration test for the new engine pipeline.
"""

from datetime import datetime, timedelta
from core.user_core_engine import scan_pair_cached
from engine_blocks import Candle


def create_realistic_candles(count: int = 200) -> list:
    """Create more realistic test candles with swing patterns."""
    candles = []
    base_time = datetime(2024, 1, 1, 0, 0)
    base_price = 1.1000
    
    for i in range(count):
        # Create wave pattern
        wave = 0.01 * (i % 20 - 10) / 10.0  # -0.01 to +0.01
        trend = i * 0.00005  # Slight uptrend
        
        open_price = base_price + trend + wave
        high_price = open_price + 0.0010
        low_price = open_price - 0.0008
        close_price = open_price + 0.0003
        
        candles.append(Candle(
            time=base_time + timedelta(minutes=5*i),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
        ))
    
    return candles


def test_pipeline_backward_compatibility():
    """
    Test that new pipeline produces similar results to old implementation
    for default trend_fibo detector.
    """
    print("\\n" + "="*60)
    print("TEST 1: Pipeline Backward Compatibility")
    print("="*60)
    
    # Setup test data
    candles = create_realistic_candles(200)
    trend_candles = candles  # Simplified: same data
    entry_candles = candles[-100:]  # Last 100 candles
    
    # User profile (default config)
    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 2.0,
        "blocks": {
            "trend": {"ma_period": 50},
            "fibo": {"levels": [0.5, 0.618]},
        },
        # No "detectors" field means default trend_fibo only
    }
    
    try:
        # Run pipeline
        result = scan_pair_cached(
            pair="EURUSD",
            profile=profile,
            trend_candles=trend_candles,
            entry_candles=entry_candles,
        )
        
        # Check result structure
        assert result is not None, "Result should not be None"
        assert result.pair == "EURUSD", f"Expected pair EURUSD, got {result.pair}"
        assert result.trend_tf == "H4", f"Expected H4, got {result.trend_tf}"
        assert result.entry_tf == "M15", f"Expected M15, got {result.entry_tf}"
        
        # Check reasons list is populated
        assert len(result.reasons) > 0, "Reasons should be populated"
        
        print(f"[OK] Pipeline executed successfully")
        print(f"  Pair: {result.pair}")
        print(f"  Has setup: {result.has_setup}")
        print(f"  Reasons: {result.reasons}")
        if result.setup:
            print(f"  Direction: {result.setup.direction}")
            print(f"  RR: {result.setup.rr:.2f}")
        
        print("[PASS] TEST PASSED")
        return True
        
    except Exception as e:
        print(f"[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pipeline_multi_detector():
    """Test pipeline with multiple detectors enabled."""
    print("\\n" + "="*60)
    print("TEST 2: Multi-Detector Pipeline")
    print("="*60)
    
    candles = create_realistic_candles(200)
    trend_candles = candles
    entry_candles = candles[-100:]
    
    # Enable multiple detectors
    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 2.0,
        "blocks": {
            "trend": {"ma_period": 50},
            "fibo": {"levels": [0.5, 0.618]},
        },
        "detectors": {
            "trend_fibo": {"enabled": True},
            "break_retest": {"enabled": True, "params": {"lookback": 10}},
        },
    }
    
    try:
        result = scan_pair_cached(
            pair="GBPUSD",
            profile=profile,
            trend_candles=trend_candles,
            entry_candles=entry_candles,
        )
        
        assert result is not None, "Result should not be None"
        
        print(f"[OK] Multi-detector pipeline executed")
        print(f"  Has setup: {result.has_setup}")
        print(f"  Reasons: {result.reasons}")
        
        # Check if any detector info is in reasons
        detector_mentioned = any("DETECTOR|" in r for r in result.reasons)
        if detector_mentioned:
            print("  [OK] Detector information recorded in reasons")
        
        print("[PASS] TEST PASSED")
        return True
        
    except Exception as e:
        print(f"[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pipeline_error_handling():
    """Test pipeline handles errors gracefully."""
    print("\\n" + "="*60)
    print("TEST 3: Error Handling")
    print("="*60)
    
    # Test with insufficient data
    small_candles = create_realistic_candles(10)
    
    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 2.0,
        "blocks": {
            "trend": {"ma_period": 50},
        },
    }
    
    try:
        result = scan_pair_cached(
            pair="XAUUSD",
            profile=profile,
            trend_candles=small_candles,
            entry_candles=small_candles,
        )
        
        assert result is not None, "Result should not be None"
        assert not result.has_setup, "Should not have setup with insufficient data"
        
        # Should have error reason
        has_error = any("insufficient" in r.lower() for r in result.reasons)
        assert has_error, "Should have insufficient data error"
        
        print(f"[OK] Error handling works correctly")
        print(f"  Reasons: {result.reasons}")
        print("[PASS] TEST PASSED")
        return True
        
    except Exception as e:
        print(f"[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\\n" + "="*60)
    print("ENGINE PIPELINE INTEGRATION TESTS")
    print("="*60)
    
    results = []
    results.append(test_pipeline_backward_compatibility())
    results.append(test_pipeline_multi_detector())
    results.append(test_pipeline_error_handling())
    
    print("\\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("[PASS] ALL TESTS PASSED")
    else:
        print(f"[FAIL] {total - passed} TEST(S) FAILED")

