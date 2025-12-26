"""
test_indicator_free_primitives.py
----------------------------------
Test indicator-free core primitives.
"""

from datetime import datetime, timedelta, timezone
from core.primitives import (
    find_fractal_swings,
    detect_structure_trend,
    build_sr_zones_from_swings,
    compute_primitives,
)
from engine_blocks import Candle


def create_trending_candles(count: int = 100, trend: str = "up"):
    """Create candles with clear trend pattern."""
    candles = []
    base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    base_price = 1.1000
    
    for i in range(count):
        candle_time = base_time + timedelta(minutes=i*5)
        
        if trend == "up":
            # Uptrend with swings
            wave = 0.005 * (i % 10 - 5) / 5.0  # Oscillation
            trend_component = i * 0.0002  # Rising
        elif trend == "down":
            wave = 0.005 * (i % 10 - 5) / 5.0
            trend_component = -i * 0.0002  # Falling
        else:  # flat/sideways
            wave = 0.005 * (i % 10 - 5) / 5.0
            trend_component = 0
        
        open_price = base_price + trend_component + wave
        high_price = open_price + 0.0005
        low_price = open_price - 0.0005
        close_price = open_price + 0.0001
        
        candles.append(Candle(
            time=candle_time,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
        ))
    
    return candles


def test_fractal_swings():
    """Test fractal swing detection."""
    print("\n" + "="*60)
    print("TEST: Fractal Swing Detection")
    print("="*60)
    
    candles = create_trending_candles(100, trend="up")
    
    swing_highs, swing_lows = find_fractal_swings(
        candles,
        left_bars=5,
        right_bars=5,
    )
    
    print(f"\nFound {len(swing_highs)} swing highs")
    print(f"Found {len(swing_lows)} swing lows")
    
    if swing_highs:
        print(f"\nFirst 3 swing highs:")
        for i, swing in enumerate(swing_highs[:3]):
            print(f"  {i+1}. Index={swing.index}, Price={swing.price:.5f}, Time={swing.time}")
    
    if swing_lows:
        print(f"\nFirst 3 swing lows:")
        for i, swing in enumerate(swing_lows[:3]):
            print(f"  {i+1}. Index={swing.index}, Price={swing.price:.5f}, Time={swing.time}")
    
    assert len(swing_highs) > 0, "Should find some swing highs"
    assert len(swing_lows) > 0, "Should find some swing lows"
    
    print("\n[PASS] Fractal swings detected")
    return True


def test_structure_trend():
    """Test structure-based trend detection."""
    print("\n" + "="*60)
    print("TEST: Structure Trend Detection")
    print("="*60)
    
    # Test uptrend
    print("\n--- Uptrend Test ---")
    up_candles = create_trending_candles(100, trend="up")
    highs, lows = find_fractal_swings(up_candles)
    up_result = detect_structure_trend(highs, lows)
    
    print(f"Direction: {up_result.direction}")
    print(f"Valid: {up_result.structure_valid}")
    print(f"HH: {up_result.hh_count}, HL: {up_result.hl_count}")
    print(f"LH: {up_result.lh_count}, LL: {up_result.ll_count}")
    
    # Test downtrend
    print("\n--- Downtrend Test ---")
    down_candles = create_trending_candles(100, trend="down")
    highs, lows = find_fractal_swings(down_candles)
    down_result = detect_structure_trend(highs, lows)
    
    print(f"Direction: {down_result.direction}")
    print(f"Valid: {down_result.structure_valid}")
    print(f"HH: {down_result.hh_count}, HL: {down_result.hl_count}")
    print(f"LH: {down_result.lh_count}, LL: {down_result.ll_count}")
    
    # Verify trends detected correctly
    assert up_result.direction in ["up", "flat"], f"Uptrend should be 'up' or 'flat', got {up_result.direction}"
    assert down_result.direction in ["down", "flat"], f"Downtrend should be 'down' or 'flat', got {down_result.direction}"
    
    print("\n[PASS] Structure trend detection works")
    return True


def test_sr_zones():
    """Test S/R zone clustering from swings."""
    print("\n" + "="*60)
    print("TEST: S/R Zone Clustering")
    print("="*60)
    
    candles = create_trending_candles(100, trend="up")
    highs, lows = find_fractal_swings(candles)
    zones = build_sr_zones_from_swings(highs, lows, cluster_tolerance=0.002)
    
    print(f"\nFound {len(zones)} S/R zones")
    
    if zones:
        print(f"\nTop 5 strongest zones:")
        for i, zone in enumerate(zones[:5]):
            zone_type = "Resistance" if zone.is_resistance else "Support"
            print(f"  {i+1}. {zone_type} @ {zone.level:.5f} (strength={zone.strength}, range={zone.lower:.5f}-{zone.upper:.5f})")
    
    assert len(zones) > 0, "Should find some S/R zones"
    
    # Check zones are sorted by strength
    if len(zones) >= 2:
        assert zones[0].strength >= zones[1].strength, "Zones should be sorted by strength"
    
    print("\n[PASS] S/R zone clustering works")
    return True


def test_compute_primitives_with_indicator_free():
    """Test that compute_primitives includes indicator-free calculations."""
    print("\n" + "="*60)
    print("TEST: compute_primitives() Integration")
    print("="*60)
    
    trend_candles = create_trending_candles(200, trend="up")
    entry_candles = create_trending_candles(100, trend="up")
    
    primitives = compute_primitives(
        trend_candles=trend_candles,
        entry_candles=entry_candles,
        trend_direction="up",
        config={},
    )
    
    print(f"\nPrimitives computed:")
    print(f"  Swing: {primitives.swing.found}")
    print(f"  S/R Zones: {len(primitives.sr_zones.zones)}")
    print(f"  Fib Levels: {len(primitives.fib_levels.retrace)} retracements")
    
    # Check indicator-free primitives
    if primitives.fractal_swings:
        print(f"  Fractal Swings: {len(primitives.fractal_swings)}")
    
    if primitives.structure_trend:
        print(f"  Structure Trend: {primitives.structure_trend.direction} (valid={primitives.structure_trend.structure_valid})")
    
    if primitives.sr_zones_clustered:
        print(f"  SR Zones Clustered: {len(primitives.sr_zones_clustered)}")
    
    assert primitives.fractal_swings is not None, "Should have fractal swings"
    assert primitives.structure_trend is not None, "Should have structure trend"
    assert primitives.sr_zones_clustered is not None, "Should have clustered zones"
    
    print("\n[PASS] Indicator-free primitives integrated")
    return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("INDICATOR-FREE PRIMITIVES TEST SUITE")
    print("="*60)
    
    results = []
    results.append(test_fractal_swings())
    results.append(test_structure_trend())
    results.append(test_sr_zones())
    results.append(test_compute_primitives_with_indicator_free())
    
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
