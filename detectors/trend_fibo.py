"""
trend_fibo.py
-------------
Trend + Fibonacci retracement detector.

This is the existing strategy migrated to the detector framework.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import (
    Candle,
    build_basic_setup_v2,
    check_fibo_retrace_zone,
    detect_trend,
)

from .base import BaseDetector, DetectorSignal


class TrendFiboDetector(BaseDetector):
    """
    Detects trend + Fibonacci retracement setup.
    
    Logic:
    1. Detect trend from higher timeframe
    2. Find swing on entry timeframe
    3. Check if price is in Fibo retracement zone
    4. Build setup with RR filter
    """
    
    name = "trend_fibo"

    doc = (
        "Trend + Fibonacci retracement setup. Uses higher-TF trend and entry-TF swing; "
        "fires when price is in a configured retrace zone and RR passes." 
    )
    params_schema = {
        "blocks.trend.ma_period": {"type": "int", "default": 50, "min": 10},
        "blocks.fibo.levels": {"type": "list[float]", "default": [0.5, 0.618]},
        "min_rr": {"type": "float", "default": 3.0, "min": 0.0},
        "min_risk": {"type": "float", "default": 0.0, "min": 0.0},
        "trend_tf": {"type": "str", "default": "H4"},
        "entry_tf": {"type": "str", "default": "M15"},
    }
    examples = [
        {
            "user_config": {
                "trend_tf": "H4",
                "entry_tf": "M15",
                "min_rr": 3.0,
                "blocks": {"trend": {"ma_period": 50}, "fibo": {"levels": [0.5, 0.618]}},
            }
        }
    ]
    
    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        """Detect trend + fibo setup."""
        
        # Import here to avoid circular dependency
        from core.primitives import PrimitiveResults
        
        if not isinstance(primitives, PrimitiveResults):
            return None
        
        # Extract config
        blocks = user_config.get("blocks", {})
        trend_cfg = blocks.get("trend", {}) or {}
        fibo_cfg = blocks.get("fibo", {}) or {}
        
        ma_period = int(trend_cfg.get("ma_period", 50))
        fibo_levels = tuple(fibo_cfg.get("levels", [0.5, 0.618]))
        min_rr = float(user_config.get("min_rr", 3.0))
        min_risk = float(user_config.get("min_risk", user_config.get("risk_pips", 0.0)))
        
        # Get timeframes for metadata
        trend_tf = str(user_config.get("trend_tf", "H4")).upper()
        entry_tf = str(user_config.get("entry_tf", "M15")).upper()
        
        # 1. Validate data sufficiency
        if len(trend_candles) < ma_period + 5:
            return None
        if len(entry_candles) < 10:
            return None
        
        # 2. Detect trend
        trend_info = detect_trend(trend_candles, ma_period=ma_period)
        if trend_info.direction == "flat":
            return None
        
        # 3. Use pre-computed swing from primitives
        if not primitives.swing.found or primitives.swing.swing is None:
            return None
        
        swing = primitives.swing.swing
        
        # 4. Check Fibo zone
        fibo_info = check_fibo_retrace_zone(
            entry_candles,
            swing,
            levels=fibo_levels,
            direction=trend_info.direction,
        )
        
        if not fibo_info.in_zone:
            return None
        
        # 5. Build setup
        setup = build_basic_setup_v2(
            pair=pair,
            swing=swing,
            trend=trend_info,
            fibo=fibo_info,
            min_rr=min_rr,
            min_risk=min_risk,
        )
        
        if setup is None or setup.rr < min_rr:
            return None
        
        # 6. Create detector signal
        reasons = [
            "TREND_OK",
            "SWING_OK",
            "FIBO_ZONE_OK",
            f"RR={setup.rr:.2f}",
        ]
        
        return DetectorSignal(
            detector_name=self.name,
            pair=pair,
            direction=setup.direction,
            entry=setup.entry,
            sl=setup.sl,
            tp=setup.tp,
            rr=setup.rr,
            strength=0.7,  # Base strength for this detector
            timeframe=entry_tf,
            reasons=reasons,
            meta={
                "trend_tf": trend_tf,
                "entry_tf": entry_tf,
                "fibo_zone_low": fibo_info.zone_low,
                "fibo_zone_high": fibo_info.zone_high,
                "swing_low": swing.low,
                "swing_high": swing.high,
            },
        )
