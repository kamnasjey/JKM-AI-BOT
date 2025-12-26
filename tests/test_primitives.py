"""
test_primitives.py
------------------
Unit tests for core primitives module.
"""

import pytest
from datetime import datetime, timedelta
from core.primitives import (
    SwingDetector,
    SRZoneDetector,
    TrendStructureDetector,
    FibLevelCalculator,
    compute_primitives,
)
from engine_blocks import Candle


def create_test_candles(count: int = 100, start_price: float = 1.1000) -> list:
    """Helper to create test candle data."""
    candles = []
    base_time = datetime(2024, 1, 1, 0, 0)
    
    for i in range(count):
        # Create simple uptrend
        open_price = start_price + (i * 0.0001)
        high_price = open_price + 0.0005
        low_price = open_price - 0.0003
        close_price = open_price + 0.0002
        
        candles.append(Candle(
            time=base_time + timedelta(minutes=5*i),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
        ))
    
    return candles


def test_swing_detector():
    """Test SwingDetector finds swings correctly."""
    candles = create_test_candles(100)
    
    # Test uptrend swing
    result = SwingDetector.detect(candles, direction="up", lookback=80)
    
    assert result is not None
    assert result.direction == "up"
    if result.found:
        assert result.swing is not None
        assert result.swing.low < result.swing.high


def test_sr_zone_detector():
    """Test SRZoneDetector identifies S/R levels."""
    candles = create_test_candles(100)
    
    result = SRZoneDetector.detect(candles, lookback=50)
    
    assert result is not None
    assert result.support > 0
    assert result.resistance > result.support
    assert len(result.zones) >= 2


def test_trend_structure_detector():
    """Test TrendStructureDetector analyzes trend."""
    candles = create_test_candles(100)
    
    result = TrendStructureDetector.detect(candles, lookback=50)
    
    assert result is not None
    assert result.direction in ["up", "down", "flat"]
    # Uptrend should have more higher highs
    if result.structure_valid and result.direction == "up":
        assert result.higher_highs > result.lower_lows


def test_fib_level_calculator():
    """Test FibLevelCalculator computes levels correctly."""
    from engine_blocks import Swing
    
    swing = Swing(low=1.1000, high=1.1100)
    
    result = FibLevelCalculator.calculate(swing, direction="up")
    
    assert result is not None
    assert len(result.retrace) > 0
    assert len(result.extensions) > 0
    
    # Check 0.5 level
    if 0.5 in result.retrace:
        expected_50 = 1.1000 + (1.1100 - 1.1000) * 0.5
        assert abs(result.retrace[0.5] - expected_50) < 0.0001


def test_compute_primitives_integration():
    """Test compute_primitives runs all primitives."""
    trend_candles = create_test_candles(200)
    entry_candles = create_test_candles(100)
    
    primitives = compute_primitives(
        trend_candles=trend_candles,
        entry_candles=entry_candles,
        trend_direction="up",
        config={},
    )
    
    assert primitives is not None
    assert primitives.swing is not None
    assert primitives.sr_zones is not None
    assert primitives.trend_structure is not None
    assert primitives.fib_levels is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
