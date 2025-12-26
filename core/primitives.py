"""
primitives.py
-------------
Core primitive calculations for trading engine pipeline.

All functions are stateless and cache-friendly.
Input: List[Candle] (from resampled cache)
Output: Dataclass results
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from engine_blocks import Candle, Direction, Swing
from core.types import Regime


# ============================================================
# Primitive Result Dataclasses
# ============================================================


@dataclass
class SwingResult:
    """Result from swing detection."""
    
    swing: Optional[Swing]
    direction: Direction
    found: bool
    

@dataclass
class SRZoneResult:
    """Support and Resistance zones."""
    
    support: float
    resistance: float
    last_close: float
    zones: List[Tuple[float, float]] = field(default_factory=list)  # [(low, high), ...]


@dataclass
class TrendStructureResult:
    """Trend structure analysis (higher highs, lower lows)."""
    
    direction: Direction
    structure_valid: bool
    higher_highs: int = 0
    lower_lows: int = 0
    

@dataclass
class FibLevelResult:
    """Fibonacci retracement and extension levels."""
    
    retrace: Dict[float, float]
    extensions: Dict[float, float]
    swing: Optional[Swing]


@dataclass
class FractalSwing:
    """A fractal swing point (high or low)."""
    
    index: int  # Index in candle list
    time: datetime
    price: float
    is_high: bool  # True for swing high, False for swing low


@dataclass
class StructureTrendResult:
    """Result from structure-based trend detection (indicator-free)."""
    
    direction: Direction
    structure_valid: bool
    swing_highs: List[FractalSwing] = field(default_factory=list)
    swing_lows: List[FractalSwing] = field(default_factory=list)
    hh_count: int = 0  # Higher Highs
    hl_count: int = 0  # Higher Lows
    lh_count: int = 0  # Lower Highs
    ll_count: int = 0  # Lower Lows


@dataclass
class StructureResult:
    """Structure analysis output that always returns a regime."""

    ok: bool
    regime: str  # TREND_BULL|TREND_BEAR|RANGE|CHOP
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SRZone:
    """A Support/Resistance zone."""
    
    level: float  # Center of zone
    lower: float  # Lower bound
    upper: float  # Upper bound
    strength: int  # Number of touches
    is_resistance: bool


@dataclass
class PrimitiveResults:
    """Container for all primitive calculation results."""
    
    swing: SwingResult
    sr_zones: SRZoneResult
    trend_structure: TrendStructureResult
    fib_levels: FibLevelResult
    fractal_swings: Optional[List[FractalSwing]] = None
    structure_trend: Optional[StructureTrendResult] = None
    sr_zones_clustered: Optional[List[SRZone]] = None
    

# ============================================================
# Swing Detection
# ============================================================


class SwingDetector:
    """Detects swing high/low from candle data."""
    
    @staticmethod
    def detect(
        candles: List[Candle],
        direction: Direction,
        lookback: int = 80,
    ) -> SwingResult:
        """
        Detect last swing based on direction.
        
        - up trend: lowest low → highest high after that low
        - down trend: highest high → lowest low after that high
        """
        from engine_blocks import find_last_swing
        
        swing = find_last_swing(candles, lookback=lookback, direction=direction)
        found = swing is not None and swing.low < swing.high
        
        return SwingResult(
            swing=swing,
            direction=direction,
            found=found,
        )


# ============================================================
# Support & Resistance Zones
# ============================================================


class SRZoneDetector:
    """Detects Support and Resistance zones."""
    
    @staticmethod
    def detect(candles: List[Candle], lookback: int = 50) -> SRZoneResult:
        """
        Find S/R zones from recent price action.
        
        Simple version: min low = support, max high = resistance
        """
        from engine_blocks import find_sr_levels
        
        sr = find_sr_levels(candles, lookback=lookback)
        
        # Create zones (can be enhanced later with clustering)
        zones = [
            (sr.support * 0.999, sr.support * 1.001),
            (sr.resistance * 0.999, sr.resistance * 1.001),
        ]
        
        return SRZoneResult(
            support=sr.support,
            resistance=sr.resistance,
            last_close=sr.last_close,
            zones=zones,
        )


# ============================================================
# Trend Structure Analysis
# ============================================================


class TrendStructureDetector:
    """Analyzes trend structure (higher highs, lower lows, etc.)."""
    
    @staticmethod
    def detect(candles: List[Candle], lookback: int = 50) -> TrendStructureResult:
        """
        Detect trend structure by counting higher highs and lower lows.
        
        Simple heuristic:
        - If we have more higher highs → uptrend structure
        - If we have more lower lows → downtrend structure
        """
        if len(candles) < 10:
            return TrendStructureResult(
                direction="flat",
                structure_valid=False,
            )
        
        segment = candles[-lookback:]
        if len(segment) < 10:
            segment = candles
        
        # Count higher highs and lower lows
        higher_highs = 0
        lower_lows = 0
        
        for i in range(1, len(segment)):
            if segment[i].high > segment[i-1].high:
                higher_highs += 1
            if segment[i].low < segment[i-1].low:
                lower_lows += 1
        
        # Determine direction
        if higher_highs > lower_lows * 1.5:
            direction: Direction = "up"
            valid = True
        elif lower_lows > higher_highs * 1.5:
            direction = "down"
            valid = True
        else:
            direction = "flat"
            valid = False
        
        return TrendStructureResult(
            direction=direction,
            structure_valid=valid,
            higher_highs=higher_highs,
            lower_lows=lower_lows,
        )


# ============================================================
# Fibonacci Level Calculator
# ============================================================


class FibLevelCalculator:
    """Calculates Fibonacci retracement and extension levels."""
    
    @staticmethod
    def calculate(
        swing: Optional[Swing],
        direction: Direction,
        retrace_levels: Tuple[float, ...] = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0),
        extension_levels: Tuple[float, ...] = (1.272, 1.618, 2.0, 2.618, 3.618),
    ) -> FibLevelResult:
        """
        Calculate Fibonacci levels from swing.
        """
        from engine_blocks import compute_fibo_levels
        
        if swing is None or swing.low >= swing.high:
            return FibLevelResult(
                retrace={},
                extensions={},
                swing=None,
            )
        
        fib = compute_fibo_levels(
            swing=swing,
            retrace_levels=retrace_levels,
            extension_levels=extension_levels,
            direction=direction,
        )
        
        return FibLevelResult(
            retrace=fib.retrace,
            extensions=fib.extensions,
            swing=swing,
        )


# ============================================================
# Main Primitive Computation Function
# ============================================================


def compute_primitives(
    trend_candles: List[Candle],
    entry_candles: List[Candle],
    trend_direction: Direction,
    config: Optional[Dict] = None,
) -> PrimitiveResults:
    """
    Compute all primitives at once.
    
    This is the main entry point for the engine pipeline.
    
    Args:
        trend_candles: Higher timeframe candles (e.g., H4)
        entry_candles: Lower timeframe candles (e.g., M15)
        trend_direction: Detected trend direction
        config: Optional configuration dict
        
    Returns:
        PrimitiveResults with all computed primitives
    """
    config = config or {}
    
    # 1. Indicator-free primitives
    # Find fractal swings (used for structure trend + clustered S/R)
    fractal_highs, fractal_lows = find_fractal_swings(
        entry_candles,
        left_bars=config.get("fractal_left_bars", 5),
        right_bars=config.get("fractal_right_bars", 5),
    )
    
    # Detect structure-based trend
    structure_result = detect_structure_trend(fractal_highs, fractal_lows)

    # If caller doesn't have a trend direction (indicator-free pipeline),
    # infer one best-effort so swing/fibo primitives remain usable.
    eff_direction: Direction = trend_direction
    if eff_direction == "flat":
        try:
            if bool(getattr(structure_result, "structure_valid", False)) and str(
                getattr(structure_result, "direction", "flat")
            ) in ("up", "down"):
                eff_direction = str(getattr(structure_result, "direction", "flat"))  # type: ignore[assignment]
        except Exception:
            eff_direction = "flat"

        if eff_direction == "flat" and entry_candles:
            try:
                first_close = float(entry_candles[0].close)
                last_close = float(entry_candles[-1].close)
                if last_close > first_close:
                    eff_direction = "up"
                elif last_close < first_close:
                    eff_direction = "down"
            except Exception:
                eff_direction = "flat"

    # 2. Swing detection (direction-sensitive)
    swing = SwingDetector.detect(
        entry_candles,
        direction=eff_direction,
        lookback=config.get("swing_lookback", 80),
    )

    # 3. S/R zones
    sr_zones = SRZoneDetector.detect(
        entry_candles,
        lookback=config.get("sr_lookback", 50),
    )

    # 4. Trend structure
    trend_structure = TrendStructureDetector.detect(
        trend_candles,
        lookback=config.get("trend_structure_lookback", 50),
    )

    # 5. Fibonacci levels
    fib_levels = FibLevelCalculator.calculate(
        swing=swing.swing,
        direction=eff_direction,
        retrace_levels=tuple(config.get("fib_retrace_levels", [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0])),
        extension_levels=tuple(config.get("fib_extension_levels", [1.272, 1.618, 2.0, 2.618, 3.618])),
    )
    
    # Build S/R zones from swings
    sr_zones_list = build_sr_zones_from_swings(
        fractal_highs,
        fractal_lows,
        cluster_tolerance=config.get("sr_cluster_tolerance", 0.002),
    )
    
    return PrimitiveResults(
        swing=swing,
        sr_zones=sr_zones,
        trend_structure=trend_structure,
        fib_levels=fib_levels,
        fractal_swings=fractal_highs + fractal_lows,  # Combined list
        structure_trend=structure_result,
        sr_zones_clustered=sr_zones_list,
    )


# ============================================================
# Indicator-Free Core Primitives
# ============================================================


def find_fractal_swings(
    candles: List[Candle],
    left_bars: int = 5,
    right_bars: int = 5,
) -> Tuple[List[FractalSwing], List[FractalSwing]]:
    """
    Find fractal swing highs and lows (indicator-free).
    
    A fractal high: candle.high > all highs within left_bars and right_bars
    A fractal low: candle.low < all lows within left_bars and right_bars
    
    Args:
        candles: List of candles
        left_bars: Number of bars to left
        right_bars: Number of bars to right
        
    Returns:
        (swing_highs, swing_lows) - Lists of FractalSwing objects
    """
    swing_highs: List[FractalSwing] = []
    swing_lows: List[FractalSwing] = []
    
    if len(candles) < left_bars + right_bars + 1:
        return swing_highs, swing_lows
    
    # Check each candle (excluding edges)
    for i in range(left_bars, len(candles) - right_bars):
        candle = candles[i]
        
        # Check for swing high
        is_swing_high = True
        for j in range(i - left_bars, i + right_bars + 1):
            if j == i:
                continue
            if candles[j].high >= candle.high:
                is_swing_high = False
                break
        
        if is_swing_high:
            swing_highs.append(FractalSwing(
                index=i,
                time=candle.time,
                price=candle.high,
                is_high=True,
            ))
        
        # Check for swing low
        is_swing_low = True
        for j in range(i - left_bars, i + right_bars + 1):
            if j == i:
                continue
            if candles[j].low <= candle.low:
                is_swing_low = False
                break
        
        if is_swing_low:
            swing_lows.append(FractalSwing(
                index=i,
                time=candle.time,
                price=candle.low,
                is_high=False,
            ))
    
    return swing_highs, swing_lows


def detect_structure_trend(
    swing_highs: List[FractalSwing],
    swing_lows: List[FractalSwing],
) -> StructureTrendResult:
    """
    Detect trend based on swing structure (HH/HL vs LH/LL).
    
    Indicator-free method:
    - Uptrend: Higher Highs (HH) and Higher Lows (HL)
    - Downtrend: Lower Highs (LH) and Lower Lows (LL)
    - Flat: Mixed or insufficient data
    
    Args:
        swing_highs: List of swing high points
        swing_lows: List of swing low points
        
    Returns:
        StructureTrendResult with direction and counts
    """
    hh_count = 0
    lh_count = 0
    hl_count = 0
    ll_count = 0
    
    # Count Higher Highs and Lower Highs
    for i in range(1, len(swing_highs)):
        if swing_highs[i].price > swing_highs[i-1].price:
            hh_count += 1
        else:
            lh_count += 1
    
    # Count Higher Lows and Lower Lows
    for i in range(1, len(swing_lows)):
        if swing_lows[i].price > swing_lows[i-1].price:
            hl_count += 1
        else:
            ll_count += 1
    
    # Determine trend
    total_highs = hh_count + lh_count
    total_lows = hl_count + ll_count
    
    if total_highs == 0 or total_lows == 0:
        direction: Direction = "flat"
        valid = False
    elif hh_count > lh_count and hl_count > ll_count:
        direction = "up"
        valid = True
    elif lh_count > hh_count and ll_count > hl_count:
        direction = "down"
        valid = True
    else:
        direction = "flat"
        valid = False
    
    return StructureTrendResult(
        direction=direction,
        structure_valid=valid,
        swing_highs=swing_highs,
        swing_lows=swing_lows,
        hh_count=hh_count,
        hl_count=hl_count,
        lh_count=lh_count,
        ll_count=ll_count,
    )


def analyze_structure(
    entry_candles: List[Candle],
    structure_trend: Optional[StructureTrendResult],
    *,
    min_swings_for_chop: int = 6,
    chop_range_width_pct: float = 0.008,
) -> StructureResult:
    """Analyze structure and classify regime.

    Indicator-free, always returns a regime.

    Heuristic:
    - If structure_trend is valid & direction up/down => TREND_BULL/TREND_BEAR
    - Else: decide CHOP vs RANGE from swing density and range width
    """
    evidence: Dict[str, Any] = {}

    if entry_candles:
        first_close = float(entry_candles[0].close)
        last_close = float(entry_candles[-1].close)
        high_max = max(float(c.high) for c in entry_candles)
        low_min = min(float(c.low) for c in entry_candles)

        denom = last_close if last_close != 0.0 else 1.0
        range_width_pct = (high_max - low_min) / denom
        slope = (last_close - first_close) / (first_close if first_close != 0.0 else 1.0)

        evidence.update(
            {
                "range_width_pct": float(range_width_pct),
                "slope": float(slope),
                "last_close": float(last_close),
            }
        )

    if structure_trend is not None:
        hh = int(getattr(structure_trend, "hh_count", 0))
        hl = int(getattr(structure_trend, "hl_count", 0))
        lh = int(getattr(structure_trend, "lh_count", 0))
        ll = int(getattr(structure_trend, "ll_count", 0))

        swing_highs = list(getattr(structure_trend, "swing_highs", []) or [])
        swing_lows = list(getattr(structure_trend, "swing_lows", []) or [])
        swing_count = int(len(swing_highs) + len(swing_lows))

        denom_dn = float(lh + ll) if (lh + ll) != 0 else 1.0
        denom_up = float(hh + hl) if (hh + hl) != 0 else 1.0
        hh_hl_ratio = float((hh + hl) / denom_dn)
        ll_lh_ratio = float((ll + lh) / denom_up)

        evidence.update(
            {
                "swing_count": swing_count,
                "hh": hh,
                "hl": hl,
                "lh": lh,
                "ll": ll,
                "hh_hl_ratio": hh_hl_ratio,
                "ll_lh_ratio": ll_lh_ratio,
                "structure_valid": bool(getattr(structure_trend, "structure_valid", False)),
                "direction": str(getattr(structure_trend, "direction", "flat")),
            }
        )

        if bool(getattr(structure_trend, "structure_valid", False)) and str(
            getattr(structure_trend, "direction", "flat")
        ) in ("up", "down"):
            direction = str(getattr(structure_trend, "direction", "flat"))
            regime = Regime.TREND_BULL.value if direction == "up" else Regime.TREND_BEAR.value
            return StructureResult(ok=True, regime=regime, evidence=evidence)

        # Mixed/unclear: classify CHOP vs RANGE
        range_width_pct = float(evidence.get("range_width_pct", 0.0) or 0.0)
        if swing_count >= int(min_swings_for_chop) and range_width_pct <= float(chop_range_width_pct):
            return StructureResult(ok=True, regime=Regime.CHOP.value, evidence=evidence)

        return StructureResult(ok=True, regime=Regime.RANGE.value, evidence=evidence)

    # No structure_trend available: conservative fallback to CHOP.
    return StructureResult(ok=True, regime=Regime.CHOP.value, evidence=evidence)


def build_sr_zones_from_swings(
    swing_highs: List[FractalSwing],
    swing_lows: List[FractalSwing],
    cluster_tolerance: float = 0.002,  # 0.2% price tolerance for clustering
) -> List[SRZone]:
    """
    Build S/R zones by clustering swing points.
    
    Swings that are within cluster_tolerance of each other are grouped
    into a single zone. Zone strength = number of touches.
    
    Args:
        swing_highs: List of swing high points
        swing_lows: List of swing low points
        cluster_tolerance: Price tolerance for clustering (as fraction, e.g., 0.002 = 0.2%)
        
    Returns:
        List of SRZone objects sorted by strength (descending)
    """
    zones: List[SRZone] = []
    
    # Process swing highs (resistance zones)
    for swing in swing_highs:
        # Check if this swing belongs to an existing zone
        found_zone = False
        for zone in zones:
            if zone.is_resistance:
                # Check if within tolerance
                if abs(swing.price - zone.level) / zone.level <= cluster_tolerance:
                    # Add to existing zone
                    zone.strength += 1
                    # Update zone bounds
                    zone.lower = min(zone.lower, swing.price * (1 - cluster_tolerance))
                    zone.upper = max(zone.upper, swing.price * (1 + cluster_tolerance))
                    # Recalculate center
                    zone.level = (zone.lower + zone.upper) / 2
                    found_zone = True
                    break
        
        if not found_zone:
            # Create new resistance zone
            zones.append(SRZone(
                level=swing.price,
                lower=swing.price * (1 - cluster_tolerance),
                upper=swing.price * (1 + cluster_tolerance),
                strength=1,
                is_resistance=True,
            ))
    
    # Process swing lows (support zones)
    for swing in swing_lows:
        found_zone = False
        for zone in zones:
            if not zone.is_resistance:
                if abs(swing.price - zone.level) / zone.level <= cluster_tolerance:
                    zone.strength += 1
                    zone.lower = min(zone.lower, swing.price * (1 - cluster_tolerance))
                    zone.upper = max(zone.upper, swing.price * (1 + cluster_tolerance))
                    zone.level = (zone.lower + zone.upper) / 2
                    found_zone = True
                    break
        
        if not found_zone:
            zones.append(SRZone(
                level=swing.price,
                lower=swing.price * (1 - cluster_tolerance),
                upper=swing.price * (1 + cluster_tolerance),
                strength=1,
                is_resistance=False,
            ))
    
    # Sort by strength (descending)
    zones.sort(key=lambda z: z.strength, reverse=True)
    
    return zones
