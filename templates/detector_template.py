"""
detector_template.py
--------------------
Template/Contract for a JKM Trading AI Detector.

Use this as a starting point for new detectors.
"""

from typing import Any, Dict, List, Optional
from detectors.base import BaseDetector, DetectorSignal, DetectorConfig
from engine_blocks import Candle

class MyNewDetector(BaseDetector):
    # Unique registry name (snake_case)
    name = "my_new_detector"
    
    # documentation string for UI/API
    doc = "Detects [Specific Pattern] to predict [Direction]."
    
    # JSON-schema compatible dictionary describing params
    params_schema = {
        "threshold": {"type": "number", "default": 1.5},
        "lookback": {"type": "integer", "default": 10},
    }
    
    # Examples for documentation/testing
    examples = [
        {"threshold": 2.0, "description": "Strict detection mode"}
    ]

    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,  # PrimitiveResults
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        """
        Main detection logic.
        
        Contract:
        - Must be deterministic (same inputs -> same output).
        - Must be NA-safe (handle missing data gracefully).
        - Return None if no signal found.
        - Return DetectorSignal if signal found.
        """
        
        # 1. Parse Params
        threshold = self.config.params.get("threshold", 1.5)
        
        # 2. Safety Checks (NA-safe)
        if not entry_candles or len(entry_candles) < 10:
            return None
            
        # 3. Logic
        last_close = entry_candles[-1].close
        
        # ... logic ...
        
        # 4. Result
        # if signal_found:
        #     return DetectorSignal(
        #         detector_name=self.name,
        #         pair=pair,
        #         direction="BUY",
        #         entry=...,
        #         sl=...,
        #         tp=...,
        #         rr=2.0,
        #         reasons=["Price crossed threshold"],
        #         meta={"custom_score": 99}
        #     )
            
        return None
