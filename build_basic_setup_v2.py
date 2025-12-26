"""build_basic_setup_v2.py
-----------------------
Risk management setup builder using primitives.

This builder is used by the indicator-free engine when a detector matches
but does not provide concrete entry/SL/TP.

No indicators; uses only price/structure primitives (S/R zones + optional swing).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.primitives import PrimitiveResults
from engine_blocks import Setup


SetupDict = Dict[str, Any]
EvidenceDict = Dict[str, Any]


# Fail reason constants (enum-like)
OK = "OK"
SETUP_BUILD_FAILED = "SETUP_BUILD_FAILED"

NO_ENTRY_TRIGGER = "NO_ENTRY_TRIGGER"
SWING_NOT_FOUND = "SWING_NOT_FOUND"
NO_INVALIDATION_LEVEL = "NO_INVALIDATION_LEVEL"
ZONE_TOO_WIDE = "ZONE_TOO_WIDE"
NO_TARGETS_FOUND = "NO_TARGETS_FOUND"
RR_BELOW_MIN = "RR_BELOW_MIN"
ENTRY_TOO_FAR = "ENTRY_TOO_FAR"


@dataclass(frozen=True)
class BuildSetupResult:
    ok: bool
    fail_reason: str
    setup: Optional[Setup]
    evidence: Dict[str, Any]


def _pip_size(pair: str) -> Optional[float]:
    p = str(pair or "").upper().replace("/", "")
    if len(p) >= 6 and p.endswith("JPY"):
        return 0.01
    if len(p) >= 6 and p.isalpha():
        return 0.0001
    return None


def build_basic_setup_v2(
    pair: str,
    direction: str,
    entry_price: float,
    primitives: PrimitiveResults,
    min_rr: float = 2.0,
    profile: Optional[Dict[str, Any]] = None,
) -> BuildSetupResult:
    """Build trade setup using primitives (indicator-free).

    Returns:
        BuildSetupResult

    Failure reasons are intentionally *actionable*:
        - NO_ENTRY_TRIGGER
        - NO_INVALIDATION_LEVEL
        - NO_TARGETS_FOUND
        - RR_BELOW_MIN
        - ZONE_TOO_WIDE
        - SWING_NOT_FOUND
    """
    profile = profile or {}

    # Evidence must be stable and complete for ops logs and Telegram explanations.
    # Keep required keys present even on early failures.
    evidence: EvidenceDict = {
        "pair": str(pair),
        "direction": str(direction),
        "entry_price": float(entry_price) if isinstance(entry_price, (int, float)) else entry_price,
        "min_rr": float(min_rr),
        # Required diagnostics (populated as we progress)
        "entry_zone": None,
        "entry_zone_width_pct": None,
        "sl": None,
        "tp": None,
        "sl_dist": None,
        "tp_dist": None,
        "rr": None,
    }

    if not isinstance(entry_price, (int, float)) or float(entry_price) <= 0:
        return BuildSetupResult(False, NO_ENTRY_TRIGGER, None, {**evidence, "why": "bad_entry_price"})

    dir_u = str(direction or "").upper().strip()
    if dir_u not in ("BUY", "SELL"):
        return BuildSetupResult(False, NO_ENTRY_TRIGGER, None, {**evidence, "why": "invalid_direction"})

    # Controls (conservative defaults to preserve current behavior)
    max_sl_dist_frac = float(profile.get("max_sl_dist_frac", 0.05))  # 5% default
    enable_rr_min_fallback_tp = bool(profile.get("enable_rr_min_fallback_tp", True))
    # Optional: if configured, reject entries that are too far from the chosen entry zone.
    # Default is None to preserve existing behavior.
    max_entry_dist_frac = profile.get("max_entry_dist_frac")
    try:
        max_entry_dist_frac_f = float(max_entry_dist_frac) if max_entry_dist_frac is not None else None
    except Exception:
        max_entry_dist_frac_f = None

    # Optional: fail early if the entry zone itself is too wide (separate from RR).
    max_entry_zone_width_pct = profile.get("max_entry_zone_width_pct")
    try:
        max_entry_zone_width_pct_f = (
            float(max_entry_zone_width_pct) if max_entry_zone_width_pct is not None else None
        )
    except Exception:
        max_entry_zone_width_pct_f = None

    # Optional: improve RR by taking entry on the more favorable zone edge when the
    # current price is touching/inside the zone.
    entry_touch_tolerance_frac = float(profile.get("entry_touch_tolerance_frac", 0.0015))
    sl_buffer_frac_of_zone = float(profile.get("sl_buffer_frac_of_zone", 0.25))

    sr_zones = primitives.sr_zones_clustered or []
    swing = primitives.swing.swing if getattr(primitives.swing, "found", False) else None

    # If clustering produced nothing, fall back to the simple SR box.
    # This preserves existing behavior where the engine can still build a setup
    # from basic support/resistance even when fractal swings are sparse.
    if not sr_zones:
        try:
            sr = primitives.sr_zones
            support = float(getattr(sr, "support", 0.0) or 0.0)
            resistance = float(getattr(sr, "resistance", 0.0) or 0.0)
            if support > 0 and resistance > 0 and resistance > support:
                evidence["sr_source"] = "simple_box"

                class _Z:  # lightweight zone shim
                    def __init__(self, level: float, is_resistance: bool):
                        self.level = level
                        self.lower = level
                        self.upper = level
                        self.strength = 1
                        self.is_resistance = is_resistance

                sr_zones = [_Z(support, False), _Z(resistance, True)]
        except Exception:
            pass

    # Choose nearest relevant S/R zones (best-effort)
    support_zones = [z for z in sr_zones if not z.is_resistance]
    resistance_zones = [z for z in sr_zones if z.is_resistance]

    chosen_support = None
    chosen_resistance = None
    if support_zones:
        support_zones.sort(key=lambda z: abs(float(z.level) - float(entry_price)))
        chosen_support = support_zones[0]
    if resistance_zones:
        resistance_zones.sort(key=lambda z: abs(float(z.level) - float(entry_price)))
        chosen_resistance = resistance_zones[0]

    entry_zone = None
    chosen_zone = None
    evidence["entry_price_input"] = float(entry_price)
    if dir_u == "BUY" and chosen_support is not None:
        entry_zone = f"support@{float(chosen_support.level):.5f}"
        chosen_zone = chosen_support
        zone_width_frac = (
            float((chosen_support.upper - chosen_support.lower) / chosen_support.level)
            if float(chosen_support.level) > 0
            else None
        )
        evidence.update(
            {
                "entry_zone": entry_zone,
                "zone_level": float(chosen_support.level),
                "zone_low": float(chosen_support.lower),
                "zone_high": float(chosen_support.upper),
                "zone_width_frac": zone_width_frac,
                "entry_zone_width_pct": (float(zone_width_frac) * 100.0) if zone_width_frac is not None else None,
            }
        )
    elif dir_u == "SELL" and chosen_resistance is not None:
        entry_zone = f"resistance@{float(chosen_resistance.level):.5f}"
        chosen_zone = chosen_resistance
        zone_width_frac = (
            float((chosen_resistance.upper - chosen_resistance.lower) / chosen_resistance.level)
            if float(chosen_resistance.level) > 0
            else None
        )
        evidence.update(
            {
                "entry_zone": entry_zone,
                "zone_level": float(chosen_resistance.level),
                "zone_low": float(chosen_resistance.lower),
                "zone_high": float(chosen_resistance.upper),
                "zone_width_frac": zone_width_frac,
                "entry_zone_width_pct": (float(zone_width_frac) * 100.0) if zone_width_frac is not None else None,
            }
        )
    else:
        evidence["entry_zone"] = None

    # Early fail: entry zone width too large (separate from RR)
    if (
        chosen_zone is not None
        and max_entry_zone_width_pct_f is not None
        and evidence.get("entry_zone_width_pct") is not None
    ):
        try:
            width_pct = float(evidence["entry_zone_width_pct"])
            zone_width_abs = float(chosen_zone.upper - chosen_zone.lower)
            evidence["zone_width_abs"] = zone_width_abs
            evidence["max_entry_zone_width_pct"] = float(max_entry_zone_width_pct_f)
            if width_pct > float(max_entry_zone_width_pct_f):
                evidence["width_pct"] = width_pct
                return BuildSetupResult(False, ZONE_TOO_WIDE, None, evidence)
        except Exception:
            pass

    # Optional ENTRY_TOO_FAR gate (only when configured)
    if max_entry_dist_frac_f is not None and evidence.get("zone_level"):
        try:
            zl = float(evidence["zone_level"])
            dist_frac = abs(float(entry_price) - zl) / zl if zl > 0 else None
            evidence["entry_to_zone_dist_frac"] = dist_frac
            if dist_frac is not None and dist_frac > float(max_entry_dist_frac_f):
                evidence["max_entry_dist_frac"] = float(max_entry_dist_frac_f)
                return BuildSetupResult(False, ENTRY_TOO_FAR, None, evidence)
        except Exception:
            pass

    # Entry improvement: if current price is touching/inside the zone, shift entry to the
    # more favorable edge (BUY: zone_low, SELL: zone_high).
    if chosen_zone is not None:
        try:
            z_low = float(chosen_zone.lower)
            z_high = float(chosen_zone.upper)
            z_level = float(chosen_zone.level) if float(chosen_zone.level) > 0 else None
            z_width_abs = float(z_high - z_low)
            if z_level and z_width_abs > 0:
                cur = float(entry_price)
                in_zone = z_low <= cur <= z_high
                touch = (
                    abs(cur - z_low) / z_level <= entry_touch_tolerance_frac
                    or abs(cur - z_high) / z_level <= entry_touch_tolerance_frac
                )
                if in_zone or touch:
                    if dir_u == "BUY":
                        entry_price = z_low
                        evidence["entry_source"] = "zone_edge_low"
                    else:
                        entry_price = z_high
                        evidence["entry_source"] = "zone_edge_high"
                    evidence["entry_price"] = float(entry_price)
                    evidence["zone_width_abs"] = z_width_abs
        except Exception:
            pass

    # Determine invalidation (SL)
    sl_level: Optional[float] = None
    if dir_u == "BUY":
        if chosen_support is not None and float(chosen_support.lower) > 0:
            sl_level = float(chosen_support.lower)
            try:
                z_width_abs = float(chosen_support.upper - chosen_support.lower)
                if z_width_abs > 0 and float(entry_price) <= float(chosen_support.lower) + 1e-12:
                    sl_level = float(chosen_support.lower) - (z_width_abs * float(sl_buffer_frac_of_zone))
                    evidence["sl_source"] = "zone_low_minus_buffer"
            except Exception:
                pass
        elif swing is not None and float(swing.low) > 0 and float(swing.low) < float(entry_price):
            sl_level = float(swing.low)
            evidence["sl_source"] = "swing_low"
    else:
        if chosen_resistance is not None and float(chosen_resistance.upper) > 0:
            sl_level = float(chosen_resistance.upper)
            try:
                z_width_abs = float(chosen_resistance.upper - chosen_resistance.lower)
                if z_width_abs > 0 and float(entry_price) >= float(chosen_resistance.upper) - 1e-12:
                    sl_level = float(chosen_resistance.upper) + (z_width_abs * float(sl_buffer_frac_of_zone))
                    evidence["sl_source"] = "zone_high_plus_buffer"
            except Exception:
                pass
        elif swing is not None and float(swing.high) > 0 and float(swing.high) > float(entry_price):
            sl_level = float(swing.high)
            evidence["sl_source"] = "swing_high"

    if sl_level is None:
        # If we don't even have a swing, make it explicit.
        if swing is None:
            return BuildSetupResult(False, SWING_NOT_FOUND, None, {**evidence, "why": "no_sl_and_no_swing"})
        return BuildSetupResult(False, NO_INVALIDATION_LEVEL, None, evidence)

    # Determine target (TP)
    tp_level: Optional[float] = None
    if dir_u == "BUY":
        candidates: list[tuple[str, float]] = []

        # SR targets (near, next, next2...)
        above = [z for z in resistance_zones if float(z.level) > float(entry_price)]
        if above:
            above.sort(key=lambda z: float(z.level))
            for z in above[:6]:
                candidates.append(("sr", float(z.level)))

        # Swing target
        if swing is not None and float(swing.high) > float(entry_price):
            candidates.append(("swing", float(swing.high)))

        # Fib extension targets
        try:
            ext = getattr(getattr(primitives, "fib_levels", None), "extensions", None)
            vals = list(ext.values()) if isinstance(ext, dict) else []
            vals = sorted({float(v) for v in vals if isinstance(v, (int, float)) and float(v) > float(entry_price)})
            for v in vals[:6]:
                candidates.append(("fib_ext", float(v)))
        except Exception:
            pass

        # Choose first target that satisfies RR>=min_rr; otherwise keep best RR.
        sl_dist_for_tp = abs(float(entry_price) - float(sl_level))
        best_rr = -1.0
        best_tp = None
        best_src = None
        for src, lvl in candidates:
            tp_dist_try = abs(float(lvl) - float(entry_price))
            rr_try = float(tp_dist_try / sl_dist_for_tp) if sl_dist_for_tp > 0 else 0.0
            if rr_try >= float(min_rr):
                tp_level = float(lvl)
                evidence["tp_source"] = f"{src}_target"
                break
            if rr_try > best_rr:
                best_rr = rr_try
                best_tp = float(lvl)
                best_src = src

        if tp_level is None and best_tp is not None:
            tp_level = best_tp
            if best_src:
                evidence["tp_source"] = f"{best_src}_best_rr"

        evidence["targets_count"] = int(len(candidates))
    else:
        candidates = []

        below = [z for z in support_zones if float(z.level) < float(entry_price)]
        if below:
            below.sort(key=lambda z: float(z.level), reverse=True)
            for z in below[:6]:
                candidates.append(("sr", float(z.level)))

        if swing is not None and float(swing.low) < float(entry_price):
            candidates.append(("swing", float(swing.low)))

        try:
            ext = getattr(getattr(primitives, "fib_levels", None), "extensions", None)
            vals = list(ext.values()) if isinstance(ext, dict) else []
            vals = sorted(
                {float(v) for v in vals if isinstance(v, (int, float)) and float(v) < float(entry_price)},
                reverse=True,
            )
            for v in vals[:6]:
                candidates.append(("fib_ext", float(v)))
        except Exception:
            pass

        sl_dist_for_tp = abs(float(entry_price) - float(sl_level))
        best_rr = -1.0
        best_tp = None
        best_src = None
        for src, lvl in candidates:
            tp_dist_try = abs(float(lvl) - float(entry_price))
            rr_try = float(tp_dist_try / sl_dist_for_tp) if sl_dist_for_tp > 0 else 0.0
            if rr_try >= float(min_rr):
                tp_level = float(lvl)
                evidence["tp_source"] = f"{src}_target"
                break
            if rr_try > best_rr:
                best_rr = rr_try
                best_tp = float(lvl)
                best_src = src

        if tp_level is None and best_tp is not None:
            tp_level = best_tp
            if best_src:
                evidence["tp_source"] = f"{best_src}_best_rr"

        evidence["targets_count"] = int(len(candidates))

    if tp_level is None:
        # Diagnostics for targets block.
        try:
            nearest_sr_level = None
            if dir_u == "BUY":
                above_levels = [float(z.level) for z in resistance_zones if float(z.level) > float(entry_price)]
                nearest_sr_level = min(above_levels) if above_levels else None
            else:
                below_levels = [float(z.level) for z in support_zones if float(z.level) < float(entry_price)]
                nearest_sr_level = max(below_levels) if below_levels else None
            evidence["nearest_sr"] = nearest_sr_level
        except Exception:
            evidence["nearest_sr"] = None

        # Count fib extension targets (best-effort; 0 when unavailable)
        try:
            ext = getattr(getattr(primitives, "fib_levels", None), "extensions", None)
            vals = list(ext.values()) if isinstance(ext, dict) else []
            vals = [float(v) for v in vals if isinstance(v, (int, float))]
            if dir_u == "BUY":
                evidence["fibo_ext_targets"] = int(sum(1 for v in vals if v > float(entry_price)))
            else:
                evidence["fibo_ext_targets"] = int(sum(1 for v in vals if v < float(entry_price)))
        except Exception:
            evidence["fibo_ext_targets"] = 0

        # If we have a valid SL but can't find a structural TP target, fall back to a
        # deterministic RR-based TP at exactly min_rr.
        # This keeps determinism guarantees for synthetic datasets while preserving
        # actionable failure reasons when SL itself can't be established.
        if enable_rr_min_fallback_tp and float(min_rr) > 0:
            sl_dist_for_tp = abs(float(entry_price) - float(sl_level))
            if sl_dist_for_tp > 0:
                if dir_u == "BUY":
                    tp_level = float(entry_price) + (sl_dist_for_tp * float(min_rr))
                else:
                    tp_level = float(entry_price) - (sl_dist_for_tp * float(min_rr))
                evidence["tp_source"] = "rr_min_fallback"
        if tp_level is None:
            if swing is None:
                return BuildSetupResult(False, SWING_NOT_FOUND, None, {**evidence, "why": "no_tp_and_no_swing"})
            return BuildSetupResult(False, NO_TARGETS_FOUND, None, evidence)

    # Distances + RR
    sl_dist = abs(float(entry_price) - float(sl_level))
    tp_dist = abs(float(tp_level) - float(entry_price))

    evidence["sl"] = float(sl_level)
    evidence["tp"] = float(tp_level)
    evidence["sl_dist"] = float(sl_dist)
    evidence["tp_dist"] = float(tp_dist)

    ps = _pip_size(pair)
    if ps:
        evidence["sl_pips"] = float(sl_dist / ps)
        evidence["tp_pips"] = float(tp_dist / ps)

    if sl_dist <= 0:
        return BuildSetupResult(False, NO_INVALIDATION_LEVEL, None, {**evidence, "why": "zero_sl_dist"})

    if float(entry_price) > 0 and (sl_dist / float(entry_price)) > max_sl_dist_frac:
        sl_dist_frac = float(sl_dist / float(entry_price))
        sl_dist_pct = float(sl_dist_frac * 100.0)
        ev = {
            **evidence,
            "max_sl_dist_frac": float(max_sl_dist_frac),
            "max_sl_dist_pct": float(max_sl_dist_frac * 100.0),
            "sl_dist_frac": sl_dist_frac,
            "sl_dist_pct": sl_dist_pct,
            # Alias for log readability (requested format: width_pct=...)
            "width_pct": sl_dist_pct,
        }
        return BuildSetupResult(False, ZONE_TOO_WIDE, None, ev)

    rr = float(tp_dist / sl_dist) if sl_dist > 0 else 0.0
    evidence["rr"] = float(rr)

    if rr < float(min_rr):
        return BuildSetupResult(False, RR_BELOW_MIN, None, evidence)

    setup = Setup(
        pair=str(pair),
        direction=dir_u,  # type: ignore[arg-type]
        entry=float(entry_price),
        sl=float(sl_level),
        tp=float(tp_level),
        rr=float(rr),
        trend_info=None,
        fibo_info=None,
    )

    return BuildSetupResult(True, OK, setup, evidence)
