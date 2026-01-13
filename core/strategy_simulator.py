"""
strategy_simulator.py
---------------------
Strategy Simulator Engine - End-to-end backtest simulation.

Rules:
- NO LOOKAHEAD: detection at candle[i] → entry at candle[i+1].open
- Intrabar ambiguity: SL_FIRST (conservative) for MVP
- One trade at a time (no overlapping positions)
- Deterministic, reproducible results
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from core.engine_blocks import Candle


# ============================================================
# Enums and Types
# ============================================================

class IntrabarPolicy(str, Enum):
    """How to resolve intrabar ambiguity when both SL and TP are hit."""
    SL_FIRST = "SL_FIRST"  # Conservative: count as loss
    TP_FIRST = "TP_FIRST"  # Optimistic: count as win
    

class RangeMode(str, Enum):
    """Time range selection mode."""
    PRESET = "PRESET"
    CUSTOM = "CUSTOM"


class RangePreset(str, Enum):
    """Preset time ranges."""
    D7 = "7D"
    D30 = "30D"
    D90 = "90D"
    M6 = "6M"
    Y1 = "1Y"


# ============================================================
# Request/Response Dataclasses
# ============================================================

@dataclass
class SimulatorRange:
    """Time range specification."""
    mode: RangeMode = RangeMode.PRESET
    preset: Optional[RangePreset] = RangePreset.D30
    from_ts: Optional[int] = None
    to_ts: Optional[int] = None
    
    def resolve(self) -> Tuple[int, int]:
        """Resolve to (from_ts, to_ts) timestamps."""
        now = int(time.time())
        
        if self.mode == RangeMode.CUSTOM:
            if self.from_ts and self.to_ts:
                return (self.from_ts, self.to_ts)
            raise ValueError("Custom range requires from_ts and to_ts")
        
        # Preset mode
        preset_seconds = {
            RangePreset.D7: 7 * 24 * 3600,
            RangePreset.D30: 30 * 24 * 3600,
            RangePreset.D90: 90 * 24 * 3600,
            RangePreset.M6: 180 * 24 * 3600,
            RangePreset.Y1: 365 * 24 * 3600,
        }
        
        preset = self.preset or RangePreset.D30
        seconds = preset_seconds.get(preset, 30 * 24 * 3600)
        
        return (now - seconds, now)


@dataclass
class SimulatorAssumptions:
    """Trading assumptions for simulation."""
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.SL_FIRST
    spread: float = 0.0  # Price units
    slippage: float = 0.0  # Price units
    commission: float = 0.0  # Per trade
    max_trades: int = 1000


@dataclass
class SimulatorRequest:
    """Request to run strategy simulation."""
    user_id: Optional[str] = None
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    range: SimulatorRange = field(default_factory=SimulatorRange)
    strategy_id: str = ""
    assumptions: SimulatorAssumptions = field(default_factory=SimulatorAssumptions)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulatorRequest":
        """Parse from API request dict."""
        range_data = data.get("range", {})
        range_obj = SimulatorRange(
            mode=RangeMode(range_data.get("mode", "PRESET")),
            preset=RangePreset(range_data.get("preset", "30D")) if range_data.get("preset") else None,
            from_ts=range_data.get("from_ts"),
            to_ts=range_data.get("to_ts"),
        )
        
        assumptions_data = data.get("assumptions", {})
        assumptions = SimulatorAssumptions(
            intrabar_policy=IntrabarPolicy(assumptions_data.get("intrabar_policy", "SL_FIRST")),
            spread=float(assumptions_data.get("spread", 0)),
            slippage=float(assumptions_data.get("slippage", 0)),
            commission=float(assumptions_data.get("commission", 0)),
            max_trades=int(assumptions_data.get("max_trades", 1000)),
        )
        
        return cls(
            user_id=data.get("user_id"),
            symbol=data.get("symbol", "XAUUSD"),
            timeframe=data.get("timeframe", "M5"),
            range=range_obj,
            strategy_id=data.get("strategy_id", ""),
            assumptions=assumptions,
        )


@dataclass
class SimulatedTrade:
    """A single simulated trade."""
    entry_ts: int
    exit_ts: int
    direction: Literal["BUY", "SELL"]
    entry: float
    sl: float
    tp: float
    outcome: Literal["TP", "SL"]
    r: float  # Risk multiple achieved
    duration_bars: int
    detector: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_ts": self.entry_ts,
            "exit_ts": self.exit_ts,
            "direction": self.direction,
            "entry": self.entry,
            "sl": self.sl,
            "tp": self.tp,
            "outcome": self.outcome,
            "r": round(self.r, 2),
            "duration_bars": self.duration_bars,
            "detector": self.detector,
            "meta": self.meta,
        }


@dataclass
class SimulatorSummary:
    """Summary metrics from simulation."""
    entries: int = 0
    tp_hits: int = 0
    sl_hits: int = 0
    winrate: float = 0.0
    avg_r: float = 0.0
    profit_factor: Optional[float] = None
    avg_duration_bars: float = 0.0
    total_r: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": self.entries,
            "tp_hits": self.tp_hits,
            "sl_hits": self.sl_hits,
            "winrate": round(self.winrate, 2),
            "avg_r": round(self.avg_r, 2),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor else None,
            "avg_duration_bars": round(self.avg_duration_bars, 1),
            "total_r": round(self.total_r, 2),
        }


@dataclass
class SimulatorResponse:
    """Response from strategy simulation."""
    ok: bool
    symbol: str = ""
    timeframe: str = ""
    from_ts: int = 0
    to_ts: int = 0
    strategy_id: str = ""
    summary: Optional[SimulatorSummary] = None
    trades: List[SimulatedTrade] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": self.ok}
        
        if not self.ok and self.error:
            result["error"] = self.error
            return result
        
        result.update({
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "from_ts": self.from_ts,
            "to_ts": self.to_ts,
            "strategy_id": self.strategy_id,
            "summary": self.summary.to_dict() if self.summary else None,
            "trades": [t.to_dict() for t in self.trades],
            "warnings": self.warnings,
        })
        
        return result


# ============================================================
# Error Codes
# ============================================================

class SimulatorError:
    """Standard error codes."""
    MISSING_CANDLES = "MISSING_CANDLES"
    NOT_ENOUGH_BARS = "NOT_ENOUGH_BARS"
    STRATEGY_NOT_FOUND = "STRATEGY_NOT_FOUND"
    INVALID_RANGE = "INVALID_RANGE"
    INVALID_DETECTOR = "INVALID_DETECTOR"
    SIMULATION_ERROR = "SIMULATION_ERROR"
    
    @staticmethod
    def make(code: str, message: str, details: Optional[Dict] = None) -> Dict[str, Any]:
        return {
            "code": code,
            "message": message,
            "details": details or {},
        }


# ============================================================
# Candle Loader
# ============================================================

def load_candles_from_cache(
    symbol: str,
    from_ts: int,
    to_ts: int,
    cache_path: Path = Path("state/market_cache.json"),
) -> Tuple[List[Candle], Optional[str]]:
    """
    Load candles from market cache.
    
    Returns:
        (candles, error_message)
    """
    if not cache_path.exists():
        return [], "Cache file not found"
    
    try:
        with open(cache_path, "r") as f:
            cache = json.load(f)
    except Exception as e:
        return [], f"Failed to read cache: {e}"
    
    # Cache format: {"version": 1, "symbols": {"XAUUSD": [...candles...], ...}}
    symbols_data = cache.get("symbols", cache)
    raw_candles = symbols_data.get(symbol, [])
    
    if not raw_candles:
        available = list(symbols_data.keys())[:5]
        return [], f"No data for {symbol}. Available: {available}"
    
    candles: List[Candle] = []
    for c in raw_candles:
        # Parse timestamp
        time_val = c.get("time", c.get("t", ""))
        if isinstance(time_val, str):
            try:
                if time_val.endswith("Z"):
                    time_val = time_val.replace("Z", "+00:00")
                dt = datetime.fromisoformat(time_val)
                ts = int(dt.timestamp())
            except:
                continue
        else:
            ts = int(time_val)
        
        # Filter by time range
        if ts < from_ts or ts > to_ts:
            continue
        
        try:
            candles.append(Candle(
                time=datetime.fromtimestamp(ts, tz=timezone.utc),
                open=float(c.get("open", c.get("o", 0))),
                high=float(c.get("high", c.get("h", 0))),
                low=float(c.get("low", c.get("l", 0))),
                close=float(c.get("close", c.get("c", 0))),
            ))
        except:
            continue
    
    # Sort by time
    candles.sort(key=lambda x: x.time)
    
    return candles, None


# ============================================================
# Strategy Loader
# ============================================================

def load_strategy(
    strategy_id: str,
    user_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Load strategy by ID.
    
    Returns:
        (strategy_dict, error_message)
    """
    # Try user strategies first
    if user_id:
        user_file = Path(f"state/user_strategies/{user_id}.json")
        if user_file.exists():
            try:
                with open(user_file, "r") as f:
                    data = json.load(f)
                strategies = data.get("strategies", [])
                for s in strategies:
                    if s.get("strategy_id") == strategy_id or s.get("id") == strategy_id:
                        return s, None
            except:
                pass
    
    # Try default/shared strategies
    shared_file = Path("state/shared_strategies.json")
    if shared_file.exists():
        try:
            with open(shared_file, "r") as f:
                strategies = json.load(f)
            for s in strategies:
                if s.get("strategy_id") == strategy_id or s.get("id") == strategy_id:
                    return s, None
        except:
            pass
    
    return None, f"Strategy '{strategy_id}' not found"


# ============================================================
# Core Simulator Engine
# ============================================================

class StrategySimulator:
    """
    Main simulator engine.
    
    Runs detectors on historical candles and simulates trades.
    """
    
    MIN_BARS = 50  # Minimum candles required
    WARMUP_BARS = 30  # Bars for detector warmup (indicator-free, so low)
    
    def __init__(self, assumptions: SimulatorAssumptions):
        self.assumptions = assumptions
        self.trades: List[SimulatedTrade] = []
        self.warnings: List[str] = []
    
    def run(
        self,
        candles: List[Candle],
        strategy: Dict[str, Any],
    ) -> SimulatorResponse:
        """
        Run simulation.
        
        Args:
            candles: Historical candles (sorted by time)
            strategy: Strategy config with 'detectors' list
            
        Returns:
            SimulatorResponse with trades and summary
        """
        from detectors.registry import DETECTOR_REGISTRY, get_detector
        from detectors.base import DetectorConfig
        
        if len(candles) < self.MIN_BARS:
            return SimulatorResponse(
                ok=False,
                error=SimulatorError.make(
                    SimulatorError.NOT_ENOUGH_BARS,
                    f"Need at least {self.MIN_BARS} candles, got {len(candles)}",
                    {"candles": len(candles), "required": self.MIN_BARS}
                ),
            )
        
        # Get detector names from strategy
        detector_names = strategy.get("detectors", [])
        if not detector_names:
            detector_names = strategy.get("rules", {}).get("detectors", [])
        
        if not detector_names:
            return SimulatorResponse(
                ok=False,
                error=SimulatorError.make(
                    SimulatorError.INVALID_DETECTOR,
                    "Strategy has no detectors configured",
                ),
            )
        
        # Validate and instantiate detectors
        detectors = []
        for name in detector_names:
            if name not in DETECTOR_REGISTRY:
                self.warnings.append(f"Unknown detector: {name}")
                continue
            
            detector = get_detector(name, DetectorConfig(enabled=True))
            if detector:
                detectors.append((name, detector))
        
        if not detectors:
            return SimulatorResponse(
                ok=False,
                error=SimulatorError.make(
                    SimulatorError.INVALID_DETECTOR,
                    f"No valid detectors found. Tried: {detector_names}",
                ),
            )
        
        # User config for detectors
        user_config = {
            "min_rr": strategy.get("min_rr", 2.0),
            "entry_tf": strategy.get("entry_tf", "M5"),
        }
        
        # Run simulation loop
        self._simulate_loop(candles, detectors, user_config)
        
        # Calculate summary
        summary = self._calculate_summary()
        
        return SimulatorResponse(
            ok=True,
            summary=summary,
            trades=self.trades,
            warnings=self.warnings,
        )
    
    def _simulate_loop(
        self,
        candles: List[Candle],
        detectors: List[Tuple[str, Any]],
        user_config: Dict[str, Any],
    ) -> None:
        """
        Main simulation loop.
        
        CRITICAL: No lookahead!
        - Detection at candle[i] uses only candles[0:i+1]
        - Entry at candle[i+1].open
        """
        from core.primitives import PrimitiveResults, SwingResult, SRZoneResult, TrendStructureResult, FibLevelResult
        from core.engine_blocks import Direction
        
        open_trade: Optional[Dict[str, Any]] = None
        trade_count = 0
        n = len(candles)
        
        for i in range(self.WARMUP_BARS, n - 1):
            # Skip if max trades reached
            if trade_count >= self.assumptions.max_trades:
                break
            
            # If we have an open trade, check for exit
            if open_trade:
                bar = candles[i]
                outcome = self._check_exit(bar, open_trade)
                
                if outcome:
                    # Close trade
                    exit_ts = int(bar.time.timestamp())
                    duration = i - open_trade["entry_index"]
                    
                    # Calculate R
                    direction = open_trade["direction"]
                    entry = open_trade["entry"]
                    sl = open_trade["sl"]
                    tp = open_trade["tp"]
                    
                    if outcome == "TP":
                        if direction == "BUY":
                            r = (tp - entry) / (entry - sl) if entry != sl else 0
                        else:
                            r = (entry - tp) / (sl - entry) if sl != entry else 0
                    else:  # SL
                        r = -1.0
                    
                    trade = SimulatedTrade(
                        entry_ts=open_trade["entry_ts"],
                        exit_ts=exit_ts,
                        direction=direction,
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        outcome=outcome,
                        r=r,
                        duration_bars=duration,
                        detector=open_trade.get("detector", ""),
                        meta=open_trade.get("meta", {}),
                    )
                    
                    self.trades.append(trade)
                    open_trade = None
                    trade_count += 1
                
                continue  # Don't look for new signals while in trade
            
            # Look for new signal
            # IMPORTANT: Use only candles up to and including i (no lookahead)
            visible_candles = candles[:i + 1]
            
            # Build minimal primitives for detectors
            primitives = self._build_primitives(visible_candles)
            
            # Try each detector
            for detector_name, detector in detectors:
                try:
                    signal = detector.detect(
                        pair="",  # Not needed for simulation
                        entry_candles=visible_candles,
                        trend_candles=visible_candles,  # Same for MVP
                        primitives=primitives,
                        user_config=user_config,
                    )
                    
                    if signal and signal.entry and signal.sl and signal.tp:
                        # Entry at NEXT bar's open (no lookahead)
                        next_bar = candles[i + 1]
                        entry_price = next_bar.open
                        
                        # Apply spread/slippage
                        if signal.direction == "BUY":
                            entry_price += self.assumptions.spread + self.assumptions.slippage
                        else:
                            entry_price -= self.assumptions.spread + self.assumptions.slippage
                        
                        # Validate SL/TP make sense
                        if signal.direction == "BUY":
                            if signal.sl >= entry_price or signal.tp <= entry_price:
                                continue
                        else:
                            if signal.sl <= entry_price or signal.tp >= entry_price:
                                continue
                        
                        open_trade = {
                            "entry_index": i + 1,
                            "entry_ts": int(next_bar.time.timestamp()),
                            "entry": entry_price,
                            "sl": signal.sl,
                            "tp": signal.tp,
                            "direction": signal.direction,
                            "detector": detector_name,
                            "meta": {"reasons": signal.reasons},
                        }
                        break  # Only one trade at a time
                        
                except Exception as e:
                    # Detector error - log and continue
                    if f"Detector {detector_name} error" not in str(self.warnings):
                        self.warnings.append(f"Detector {detector_name} error: {str(e)[:50]}")
    
    def _check_exit(
        self,
        bar: Candle,
        trade: Dict[str, Any],
    ) -> Optional[Literal["TP", "SL"]]:
        """
        Check if trade hits TP or SL on this bar.
        
        Intrabar policy: SL_FIRST (conservative)
        """
        direction = trade["direction"]
        sl = trade["sl"]
        tp = trade["tp"]
        
        if direction == "BUY":
            hit_tp = bar.high >= tp
            hit_sl = bar.low <= sl
        else:  # SELL
            hit_tp = bar.low <= tp
            hit_sl = bar.high >= sl
        
        if hit_tp and hit_sl:
            # Both hit - use policy
            if self.assumptions.intrabar_policy == IntrabarPolicy.SL_FIRST:
                return "SL"
            else:
                return "TP"
        elif hit_tp:
            return "TP"
        elif hit_sl:
            return "SL"
        
        return None
    
    def _build_primitives(self, candles: List[Candle]) -> Any:
        """Build primitives for detectors using the real compute_primitives."""
        from core.primitives import compute_primitives
        
        if len(candles) < 20:
            return None
        
        try:
            # Use the same primitives as the production engine
            primitives = compute_primitives(
                trend_candles=candles,
                entry_candles=candles,
                trend_direction="flat",  # Will be inferred from structure
                config={
                    "fractal_left_bars": 3,  # Faster for simulation
                    "fractal_right_bars": 3,
                    "swing_lookback": min(80, len(candles) - 1),
                    "sr_lookback": min(50, len(candles) - 1),
                },
            )
            return primitives
        except Exception:
            # Fallback to None if primitives fail
            return None
    
    def _calculate_summary(self) -> SimulatorSummary:
        """Calculate summary metrics from trades."""
        if not self.trades:
            return SimulatorSummary()
        
        entries = len(self.trades)
        tp_hits = sum(1 for t in self.trades if t.outcome == "TP")
        sl_hits = sum(1 for t in self.trades if t.outcome == "SL")
        winrate = (tp_hits / entries * 100) if entries > 0 else 0
        
        # R metrics
        total_r = sum(t.r for t in self.trades)
        avg_r = total_r / entries if entries > 0 else 0
        
        # Profit factor
        gains = sum(t.r for t in self.trades if t.r > 0)
        losses = abs(sum(t.r for t in self.trades if t.r < 0))
        profit_factor = (gains / losses) if losses > 0 else None
        
        # Duration
        total_duration = sum(t.duration_bars for t in self.trades)
        avg_duration = total_duration / entries if entries > 0 else 0
        
        return SimulatorSummary(
            entries=entries,
            tp_hits=tp_hits,
            sl_hits=sl_hits,
            winrate=winrate,
            avg_r=avg_r,
            profit_factor=profit_factor,
            avg_duration_bars=avg_duration,
            total_r=total_r,
        )


# ============================================================
# Main API Function
# ============================================================

def run_simulation(request: SimulatorRequest) -> SimulatorResponse:
    """
    Run strategy simulation.
    
    This is the main entry point for the API endpoint.
    """
    # Resolve time range
    try:
        from_ts, to_ts = request.range.resolve()
    except ValueError as e:
        return SimulatorResponse(
            ok=False,
            error=SimulatorError.make(
                SimulatorError.INVALID_RANGE,
                str(e),
            ),
        )
    
    # Validate range
    if from_ts >= to_ts:
        return SimulatorResponse(
            ok=False,
            error=SimulatorError.make(
                SimulatorError.INVALID_RANGE,
                "from_ts must be less than to_ts",
            ),
        )
    
    # Load strategy
    strategy, error = load_strategy(request.strategy_id, request.user_id)
    if error:
        return SimulatorResponse(
            ok=False,
            error=SimulatorError.make(
                SimulatorError.STRATEGY_NOT_FOUND,
                error,
            ),
        )
    
    # Load candles
    candles, error = load_candles_from_cache(request.symbol, from_ts, to_ts)
    if error:
        return SimulatorResponse(
            ok=False,
            error=SimulatorError.make(
                SimulatorError.MISSING_CANDLES,
                error,
            ),
        )
    
    # Run simulation
    simulator = StrategySimulator(request.assumptions)
    response = simulator.run(candles, strategy)
    
    # Fill in metadata
    response.symbol = request.symbol
    response.timeframe = request.timeframe
    response.from_ts = from_ts
    response.to_ts = to_ts
    response.strategy_id = request.strategy_id
    
    return response
