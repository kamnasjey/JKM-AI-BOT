"""
test_detector_plugins.py
------------------------
Test the new detector plugin architecture.
"""

from datetime import datetime, timedelta, timezone
from engine_blocks import Candle
from core.primitives import compute_primitives
from engines.detectors import detector_registry


def create_test_candles(count: int = 100, pattern: str = "uptrend"):
    """Create test candles with specific pattern."""
    candles = []
    base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    base_price = 1.1000
    
    for i in range(count):
        candle_time = base_time + timedelta(minutes=i*5)
        
        if pattern == "uptrend":
            wave = 0.005 * (i % 10 - 5) / 5.0
            trend_component = i * 0.0002
        elif pattern == "downtrend":
            wave = 0.005 * (i % 10 - 5) / 5.0
            trend_component = -i * 0.0002
        elif pattern == "sr_bounce":
            # Price bounces between 1.10 and 1.11
            wave = 0.005 *  ((i % 20) / 10.0 - 1.0)
            trend_component = 0
        else:
            wave = 0
            trend_component = 0
        
        open_price = base_price + trend_component + wave
        high_price = open_price + 0.0008
        low_price = open_price - 0.0008
        close_price = open_price + 0.0003
        
        candles.append(Candle(
            time=candle_time,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
        ))
    
    return candles


def test_detector_registry():
    """Test detector registry listing."""
    print("\n" + "="*60)
    print("TEST: Detector Registry")
    print("="*60)
    
    detectors = detector_registry.list_detectors()
    
    print(f"\nRegistered detectors ({len(detectors)}):")
    for name in sorted(detectors):
        detector_class = detector_registry.get_detector_class(name)
        if detector_class:
            print(f"  - {name}: {detector_class.description}")
    
    assert len(detectors) > 0, "Should have registered detectors"
    assert "sr_bounce" in detectors, "SR bounce should be registered"
    assert "pinbar" in detectors, "Pinbar should be registered"
    assert "fibo_retrace" in detectors, "Fibo retrace should be registered"
    assert "structure_trend" in detectors, "Structure trend should be registered"
    
    print("\n[PASS] Registry working correctly")
    return True


def test_sr_bounce_detector():
    """Test S/R bounce detector."""
    print("\n" + "="*60)
    print("TEST: S/R Bounce Detector")
    print("="*60)
    
    candles = create_test_candles(100, pattern="sr_bounce")
    
    # Compute primitives
    primitives = compute_primitives(
        trend_candles=candles,
        entry_candles=candles,
        trend_direction="flat",
        config={},
    )
    
    # Create detector
    detector = detector_registry.create_detector("sr_bounce", {"enabled": True})
    
    if detector:
        result = detector.detect(candles, primitives)
        
        print(f"\nDetector: {result.detector_name}")
        print(f"Match: {result.match}")
        if result.match:
            print(f"Direction: {result.direction}")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Evidence: {result.evidence}")
        
        print("\n[PASS] SR bounce detector executed")
    
    return True


def test_structure_trend_detector():
    """Test structure trend detector."""
    print("\n" + "="*60)
    print("TEST: Structure Trend Detector")
    print("="*60)
    
    candles = create_test_candles(100, pattern="uptrend")
    
    primitives = compute_primitives(
        trend_candles=candles,
        entry_candles=candles,
        trend_direction="up",
        config={},
    )
    
    detector = detector_registry.create_detector("structure_trend", {"enabled": True})
    
    if detector:
        result = detector.detect(candles, primitives)
        
        print(f"\nDetector: {result.detector_name}")
        print(f"Match: {result.match}")
        if result.match:
            print(f"Direction: {result.direction}")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Evidence: {result.evidence}")
            
            assert result.direction == "BUY", "Should detect uptrend as BUY"
        
        print("\n[PASS] Structure trend detector executed")
    
    return True


def test_load_from_profile():
    """Test loading detectors from user profile."""
    print("\n" + "="*60)
    print("TEST: Load Detectors from Profile")
    print("="*60)
    
    profile = {
        "detectors": {
            "sr_bounce": {"enabled": True},
            "pinbar": {"enabled": True},
            "structure_trend": {"enabled": True},
            "sr_breakout": {"enabled": False},  # Disabled
        }
    }
    
    detectors = detector_registry.load_from_profile(profile)
    
    print(f"\nLoaded {len(detectors)} enabled detectors:")
    for detector in detectors:
        print(f"  - {detector.name}: {detector.description}")
    
    assert len(detectors) == 3, "Should load 3 enabled detectors"
    detector_names = [d.name for d in detectors]
    assert "sr_bounce" in detector_names
    assert "pinbar" in detector_names
    assert "structure_trend" in detector_names
    assert "sr_breakout" not in detector_names, "Disabled detector should not load"
    
    print("\n[PASS] Profile loading works correctly")
    return True


def test_run_all_detectors():
    """Test running multiple detectors."""
    print("\n" + "="*60)
    print("TEST: Run All Detectors")
    print("="*60)
    
    candles = create_test_candles(100, pattern="uptrend")
    
    primitives = compute_primitives(
        trend_candles=candles,
        entry_candles=candles,
        trend_direction="up",
        config={},
    )
    
    # Load all enabled detectors
    profile = {
        "detectors": {
            "sr_bounce": {"enabled": True},
            "pinbar": {"enabled": True},
            "structure_trend": {"enabled": True},
            "fibo_retrace": {"enabled": True},
        }
    }
    
    detectors = detector_registry.load_from_profile(profile)
    results = detector_registry.run_all(detectors, candles, primitives)
    
    print(f"\nRan {len(detectors)} detectors, found {len(results)} matches:")
    for result in results:
        print(f"  - {result.detector_name}: {result.direction} (conf={result.confidence:.2f})")
        print(f"    Evidence: {result.evidence}")
    
    print("\n[PASS] Running multiple detectors works")
    return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("DETECTOR PLUGIN ARCHITECTURE TEST SUITE")
    print("="*60)
    
    results = []
    results.append(test_detector_registry())
    results.append(test_sr_bounce_detector())
    results.append(test_structure_trend_detector())
    results.append(test_load_from_profile())
    results.append(test_run_all_detectors())
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("[PASS] ALL TESTS PASSED")
    else:
        print(f"[FAIL] {total - passed} TEST(S) FAILED")
