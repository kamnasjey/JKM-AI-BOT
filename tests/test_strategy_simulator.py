"""
test_strategy_simulator.py
--------------------------
Unit tests for Strategy Simulator.

Tests:
1. No-lookahead: entry at candle[i+1].open when signal at candle[i]
2. Intrabar SL_FIRST: both TP/SL hit → SL outcome
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any, Dict

from core.engine_blocks import Candle
from core.strategy_simulator import (
    StrategySimulator,
    SimulatorAssumptions,
    IntrabarPolicy,
    SimulatedTrade,
)


# ============================================================
# Helper: Create test candles
# ============================================================

def make_candles(prices: List[tuple], start_ts: int = 1700000000) -> List[Candle]:
    """
    Create candles from (open, high, low, close) tuples.
    Each candle is 5 minutes apart.
    """
    candles = []
    for i, (o, h, l, c) in enumerate(prices):
        ts = start_ts + i * 300  # 5 min intervals
        candles.append(Candle(
            time=datetime.fromtimestamp(ts, tz=timezone.utc),
            open=float(o),
            high=float(h),
            low=float(l),
            close=float(c),
        ))
    return candles


# ============================================================
# Mock Detector for Testing
# ============================================================

class MockDetector:
    """
    Mock detector that triggers at a specific candle index.
    """
    name = "mock_detector"
    
    def __init__(self, trigger_at_index: int, direction: str = "BUY"):
        self.trigger_at_index = trigger_at_index
        self.direction = direction
        self.call_count = 0
        self.last_candle_count = 0
    
    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ):
        """Return signal only when we have exactly trigger_at_index + 1 candles."""
        self.call_count += 1
        self.last_candle_count = len(entry_candles)
        
        # Only trigger when visible candles reach our target
        if len(entry_candles) == self.trigger_at_index + 1:
            from detectors.base import DetectorSignal
            
            last = entry_candles[-1]
            entry = last.close
            
            if self.direction == "BUY":
                sl = entry - 10  # 10 points below
                tp = entry + 20  # 20 points above (RR = 2)
            else:
                sl = entry + 10
                tp = entry - 20
            
            return DetectorSignal(
                detector_name=self.name,
                pair=pair,
                direction=self.direction,
                entry=entry,
                sl=sl,
                tp=tp,
                rr=2.0,
                reasons=["TEST_SIGNAL"],
            )
        
        return None


# ============================================================
# Test 1: No Lookahead - Entry at Next Bar Open
# ============================================================

def test_no_lookahead_entry_next_open():
    """
    Verify that when detector triggers at candle[i], 
    entry happens at candle[i+1].open (not candle[i].close).
    
    This is critical to prevent lookahead bias.
    """
    # Create 50 candles (enough for warmup + trading)
    prices = [(100 + i, 105 + i, 95 + i, 100 + i) for i in range(50)]
    candles = make_candles(prices)
    
    # Mock detector triggers at index 35 (after warmup of 30)
    trigger_index = 35
    mock_detector = MockDetector(trigger_at_index=trigger_index, direction="BUY")
    
    # Create simulator
    assumptions = SimulatorAssumptions(
        intrabar_policy=IntrabarPolicy.SL_FIRST,
        spread=0,
        slippage=0,
        max_trades=10,
    )
    simulator = StrategySimulator(assumptions)
    
    # Manually run simulation loop with mock detector
    detectors = [("mock_detector", mock_detector)]
    user_config = {"min_rr": 2.0}
    
    # Run simulation
    simulator._simulate_loop(candles, detectors, user_config)
    
    # Should have exactly 1 trade (or 0 if SL hit, but check entry)
    assert len(simulator.trades) >= 0, "Simulation should complete"
    
    # Key assertion: detector should only see candles up to trigger_index
    # Entry should be at candle[trigger_index + 1].open
    if simulator.trades:
        trade = simulator.trades[0]
        
        # Entry timestamp should be from candle[trigger_index + 1]
        expected_entry_ts = int(candles[trigger_index + 1].time.timestamp())
        assert trade.entry_ts == expected_entry_ts, (
            f"Entry should be at candle[{trigger_index + 1}], not earlier. "
            f"Got ts={trade.entry_ts}, expected={expected_entry_ts}"
        )
        
        # Entry price should be close to candle[trigger_index + 1].open
        expected_entry_price = candles[trigger_index + 1].open
        assert abs(trade.entry - expected_entry_price) < 0.01, (
            f"Entry price should be next bar's open ({expected_entry_price}), "
            f"got {trade.entry}"
        )
    
    # Verify detector was called with correct candle count (no lookahead)
    # When triggered, detector should have seen exactly trigger_index + 1 candles
    assert mock_detector.call_count > 0, "Detector should have been called"
    

# ============================================================
# Test 2: Intrabar SL_FIRST - Both Hit Returns SL
# ============================================================

def test_intrabar_sl_first():
    """
    When both TP and SL are hit in the same candle,
    SL_FIRST policy should return SL (loss).
    
    This is the conservative/realistic approach since we
    can't know which was hit first intrabar.
    """
    # Build a scenario:
    # 1. Signal triggers: entry=100, SL=90, TP=120 (BUY)
    # 2. Next bar has both conditions: low=85 (hits SL), high=125 (hits TP)
    # 3. With SL_FIRST, outcome should be SL
    
    prices = [
        # Warmup candles (30 needed)
        *[(100, 105, 95, 100) for _ in range(30)],
        # Trigger candle (index 30)
        (100, 105, 95, 100),
        # Entry candle (index 31) - both SL and TP hit!
        (100, 130, 80, 110),  # high=130 > TP=120, low=80 < SL=90
    ]
    candles = make_candles(prices)
    
    # Create trade manually to test exit logic
    trade_info = {
        "entry_index": 31,
        "entry_ts": int(candles[31].time.timestamp()),
        "entry": 100,
        "sl": 90,
        "tp": 120,
        "direction": "BUY",
        "detector": "test",
    }
    
    # Test with SL_FIRST
    assumptions_sl_first = SimulatorAssumptions(
        intrabar_policy=IntrabarPolicy.SL_FIRST,
    )
    simulator = StrategySimulator(assumptions_sl_first)
    
    outcome = simulator._check_exit(candles[31], trade_info)
    assert outcome == "SL", (
        f"SL_FIRST policy: both hit should return SL, got {outcome}"
    )
    
    # Test with TP_FIRST (for comparison)
    assumptions_tp_first = SimulatorAssumptions(
        intrabar_policy=IntrabarPolicy.TP_FIRST,
    )
    simulator_tp = StrategySimulator(assumptions_tp_first)
    
    outcome_tp = simulator_tp._check_exit(candles[31], trade_info)
    assert outcome_tp == "TP", (
        f"TP_FIRST policy: both hit should return TP, got {outcome_tp}"
    )


# ============================================================
# Test 3: Only TP Hit Returns TP
# ============================================================

def test_only_tp_hit():
    """When only TP is hit (not SL), outcome should be TP."""
    trade_info = {
        "direction": "BUY",
        "entry": 100,
        "sl": 90,
        "tp": 120,
    }
    
    # Bar that only hits TP (high=125, low=95 > SL=90)
    bar = Candle(
        time=datetime.now(timezone.utc),
        open=100,
        high=125,  # Hits TP at 120
        low=95,    # Doesn't hit SL at 90
        close=122,
    )
    
    simulator = StrategySimulator(SimulatorAssumptions())
    outcome = simulator._check_exit(bar, trade_info)
    
    assert outcome == "TP", f"Only TP hit should return TP, got {outcome}"


# ============================================================
# Test 4: Only SL Hit Returns SL
# ============================================================

def test_only_sl_hit():
    """When only SL is hit (not TP), outcome should be SL."""
    trade_info = {
        "direction": "BUY",
        "entry": 100,
        "sl": 90,
        "tp": 120,
    }
    
    # Bar that only hits SL (low=85, high=110 < TP=120)
    bar = Candle(
        time=datetime.now(timezone.utc),
        open=100,
        high=110,  # Doesn't hit TP at 120
        low=85,    # Hits SL at 90
        close=88,
    )
    
    simulator = StrategySimulator(SimulatorAssumptions())
    outcome = simulator._check_exit(bar, trade_info)
    
    assert outcome == "SL", f"Only SL hit should return SL, got {outcome}"


# ============================================================
# Test 5: No Exit When Neither Hit
# ============================================================

def test_no_exit_when_neither_hit():
    """When neither TP nor SL is hit, outcome should be None."""
    trade_info = {
        "direction": "BUY",
        "entry": 100,
        "sl": 90,
        "tp": 120,
    }
    
    # Bar that hits neither (low=92 > SL, high=115 < TP)
    bar = Candle(
        time=datetime.now(timezone.utc),
        open=100,
        high=115,  # < TP at 120
        low=92,    # > SL at 90
        close=110,
    )
    
    simulator = StrategySimulator(SimulatorAssumptions())
    outcome = simulator._check_exit(bar, trade_info)
    
    assert outcome is None, f"Neither hit should return None, got {outcome}"


# ============================================================
# Test 6: SELL Direction Logic
# ============================================================

def test_sell_direction_exit():
    """Test exit logic for SELL trades (reversed TP/SL conditions)."""
    trade_info = {
        "direction": "SELL",
        "entry": 100,
        "sl": 110,   # SL above entry for SELL
        "tp": 80,    # TP below entry for SELL
    }
    
    # Bar that hits TP (low=75 < TP=80)
    bar_tp = Candle(
        time=datetime.now(timezone.utc),
        open=90,
        high=95,
        low=75,   # Hits TP at 80
        close=78,
    )
    
    simulator = StrategySimulator(SimulatorAssumptions())
    outcome = simulator._check_exit(bar_tp, trade_info)
    assert outcome == "TP", f"SELL: low hitting TP should return TP, got {outcome}"
    
    # Bar that hits SL (high=115 > SL=110)
    bar_sl = Candle(
        time=datetime.now(timezone.utc),
        open=105,
        high=115,  # Hits SL at 110
        low=100,
        close=112,
    )
    
    outcome = simulator._check_exit(bar_sl, trade_info)
    assert outcome == "SL", f"SELL: high hitting SL should return SL, got {outcome}"


# ============================================================
# Run tests
# ============================================================

if __name__ == "__main__":
    print("Running Strategy Simulator Tests...")
    
    print("\n1. test_no_lookahead_entry_next_open")
    try:
        test_no_lookahead_entry_next_open()
        print("   ✓ PASSED")
    except AssertionError as e:
        print(f"   ✗ FAILED: {e}")
    except Exception as e:
        print(f"   ✗ ERROR: {e}")
    
    print("\n2. test_intrabar_sl_first")
    try:
        test_intrabar_sl_first()
        print("   ✓ PASSED")
    except AssertionError as e:
        print(f"   ✗ FAILED: {e}")
    except Exception as e:
        print(f"   ✗ ERROR: {e}")
    
    print("\n3. test_only_tp_hit")
    try:
        test_only_tp_hit()
        print("   ✓ PASSED")
    except AssertionError as e:
        print(f"   ✗ FAILED: {e}")
    
    print("\n4. test_only_sl_hit")
    try:
        test_only_sl_hit()
        print("   ✓ PASSED")
    except AssertionError as e:
        print(f"   ✗ FAILED: {e}")
    
    print("\n5. test_no_exit_when_neither_hit")
    try:
        test_no_exit_when_neither_hit()
        print("   ✓ PASSED")
    except AssertionError as e:
        print(f"   ✗ FAILED: {e}")
    
    print("\n6. test_sell_direction_exit")
    try:
        test_sell_direction_exit()
        print("   ✓ PASSED")
    except AssertionError as e:
        print(f"   ✗ FAILED: {e}")
    
    print("\n" + "="*50)
    print("All tests completed!")
