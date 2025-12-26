"""
test_detectors.py
-----------------
Unit tests for detector framework.
"""

import pytest
from datetime import datetime, timedelta
from detectors.trend_fibo import TrendFiboDetector
from detectors.break_retest import BreakRetestDetector
from detectors.pinbar_at_level import PinbarAtLevelDetector
from detectors.registry import get_detector, get_enabled_detectors, DETECTOR_REGISTRY
from detectors.base import DetectorConfig
from engine_blocks import Candle
from core.primitives import compute_primitives


def create_test_candles(count: int = 100, trend: str = "up") -> list:
    """Helper to create test candle data with trend."""
    candles = []
    base_time = datetime(2024, 1, 1, 0, 0)
    start_price = 1.1000
    
    for i in range(count):
        if trend == "up":
            open_price = start_price + (i * 0.0002)
        elif trend == "down":
            open_price = start_price - (i * 0.0002)
        else:  # flat
            open_price = start_price
        
        high_price = open_price + 0.0005
        low_price = open_price - 0.0003
        close_price = open_price + 0.0002 if trend == "up" else open_price - 0.0002
        
        candles.append(Candle(
            time=base_time + timedelta(minutes=5*i),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
        ))
    
    return candles


def test_detector_registry():
    """Test detector registry contains expected detectors."""
    assert "trend_fibo" in DETECTOR_REGISTRY
    assert "break_retest" in DETECTOR_REGISTRY
    assert "pinbar_at_level" in DETECTOR_REGISTRY
    
    # Test get_detector
    detector = get_detector("trend_fibo")
    assert detector is not None
    assert isinstance(detector, TrendFiboDetector)
    
    # Test unknown detector
    unknown = get_detector("unknown_detector")
    assert unknown is None


def test_get_enabled_detectors():
    """Test get_enabled_detectors filters correctly."""
    # Test with no config (should return default)
    detectors = get_enabled_detectors({}, default_enabled=["trend_fibo"])
    assert len(detectors) == 1
    assert "trend_fibo" in detectors
    
    # Test with custom config
    config = {
        "trend_fibo": {"enabled": True},
        "break_retest": {"enabled": True},
        "pinbar_at_level": {"enabled": False},
    }
    detectors = get_enabled_detectors(config)
    assert len(detectors) == 2
    assert "trend_fibo" in detectors
    assert "break_retest" in detectors
    assert "pinbar_at_level" not in detectors


def test_trend_fibo_detector():
    """Test TrendFiboDetector produces signals."""
    detector = TrendFiboDetector()
    
    trend_candles = create_test_candles(200, trend="up")
    entry_candles = create_test_candles(100, trend="up")
    
    primitives = compute_primitives(
        trend_candles=trend_candles,
        entry_candles=entry_candles,
        trend_direction="up",
        config={},
    )
    
    user_config = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 2.0,
        "blocks": {
            "trend": {"ma_period": 50},
            "fibo": {"levels": [0.5, 0.618]},
        },
    }
    
    signal = detector.detect(
        pair="EURUSD",
        entry_candles=entry_candles,
        trend_candles=trend_candles,
        primitives=primitives,
        user_config=user_config,
    )
    
    # Signal may or may not be generated depending on conditions
    # Just verify no exceptions and correct type
    if signal:
        assert signal.detector_name == "trend_fibo"
        assert signal.pair == "EURUSD"
        assert signal.direction in ["BUY", "SELL"]
        assert signal.rr > 0


def test_detector_enable_disable():
    """Test detectors can be enabled/disabled via config."""
    config = DetectorConfig(enabled=False)
    detector = TrendFiboDetector(config=config)
    
    assert not detector.is_enabled()
    
    config_enabled = DetectorConfig(enabled=True)
    detector_enabled = TrendFiboDetector(config=config_enabled)
    
    assert detector_enabled.is_enabled()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
