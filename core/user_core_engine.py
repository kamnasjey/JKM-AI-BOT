# user_core_engine.py
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

# No IG Client import here!
from engine_blocks import (
    detect_trend,
    find_last_swing,
    check_fibo_retrace_zone,
    build_basic_setup,
    Setup,
    TrendInfo,
    FiboZoneInfo,
    Candle,
    Swing,
    Direction,
)

from core.primitives import compute_primitives, PrimitiveResults
from detectors.registry import get_enabled_detectors
from detectors.base import DetectorSignal
from rr_filter import score_and_rank_signals

from engine.utils.params_utils import merge_param_layers, sanitize_params, stable_params_digest

@dataclass
class ScanResult:
    pair: str
    has_setup: bool
    setup: Optional[Setup]
    reasons: List[str]
    trend_info: Optional[TrendInfo] = None
    fibo_info: Optional[FiboZoneInfo] = None
    trend_tf: str = "H4"
    entry_tf: str = "M15"
    strategy_name: Optional[str] = None
    debug: Optional[Dict[str, Any]] = None


_STRATEGY_ID_SAFE_RE = re.compile(r"[^a-z0-9_\-]+")


def _slugify_strategy_id(value: str) -> str:
    s = (value or "").strip().lower().replace(" ", "_")
    s = _STRATEGY_ID_SAFE_RE.sub("", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _coerce_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _normalize_strategy_spec(raw: Dict[str, Any], *, idx: int) -> Dict[str, Any]:
    """Normalize a user strategy dict to StrategySpec v1 (best-effort, backward compatible)."""
    s: Dict[str, Any] = dict(raw or {})

    # enabled
    s["enabled"] = _coerce_bool(s.get("enabled"), True)

    # strategy_id
    sid = str(s.get("strategy_id") or "").strip()
    if not sid:
        base = _slugify_strategy_id(str(s.get("name") or ""))
        if not base:
            base = f"strategy_{idx + 1}"
        # Add a short suffix for stability/uniqueness when names collide.
        suffix_src = f"{base}:{idx}:{s.get('name') or ''}"
        suffix = hashlib.sha1(suffix_src.encode("utf-8")).hexdigest()[:6]
        sid = f"{base}_{suffix}"
    s["strategy_id"] = sid

    # detectors allow-list: accept list[str] and convert to dict config.
    dets = s.get("detectors")
    if isinstance(dets, list):
        det_cfg: Dict[str, Any] = {}
        for name in dets:
            dn = str(name or "").strip()
            if dn:
                det_cfg[dn] = {"enabled": True}
        s["detectors"] = det_cfg

    # allowed_regimes: normalize to list[str] of canonical tokens.
    ar = s.get("allowed_regimes")
    if isinstance(ar, (list, tuple)):
        norm = []
        for x in ar:
            xs = str(x or "").strip().upper()
            if xs:
                norm.append(xs)
        s["allowed_regimes"] = norm

    # weights should be a dict if provided.
    if "weights" in s and not isinstance(s.get("weights"), dict):
        s["weights"] = {}

    return s


def extract_strategy_configs(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a list of strategy configs from a user profile.

    Backward compatible:
    - If profile has `strategies` (list), returns those.
    - Otherwise returns a single config based on profile itself.
    """
    # Preferred: a single active strategy
    strategy = profile.get("strategy")
    if isinstance(strategy, dict) and strategy:
        normalized = _normalize_strategy_spec(strategy, idx=0)
        if bool(normalized.get("enabled", True)):
            return [normalized]

    # Backward compatibility: older profiles may have `strategies` list
    strategies = profile.get("strategies")
    if isinstance(strategies, list) and strategies:
        out: List[Dict[str, Any]] = []
        for i, s in enumerate(strategies):
            if not isinstance(s, dict) or not s:
                continue
            normalized = _normalize_strategy_spec(s, idx=i)
            if bool(normalized.get("enabled", True)):
                out.append(normalized)
        if out:
            return out

    # Default: require explicit strategies.
    # Legacy fallback can be re-enabled for debugging/back-compat.
    allow_fallback = str(os.getenv("ALLOW_PROFILE_STRATEGY_FALLBACK", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if allow_fallback:
        return [_normalize_strategy_spec(profile, idx=0)]
    return []


# --- Sub-routines for decomposing core logic ---

def _validate_data_sufficiency(
    trend_c: List[Candle], entry_c: List[Candle], ma_period: int
) -> Optional[str]:
    if len(trend_c) < ma_period + 5:
        return f"Trend data insufficient: {len(trend_c)} < {ma_period + 5}"
    if len(entry_c) < 10:
        return f"Entry data insufficient: {len(entry_c)} < 10"
    return None


def _analyze_trend_step(
    candles: List[Candle], ma_period: int
) -> Tuple[TrendInfo, Optional[str]]:
    info = detect_trend(candles, ma_period=ma_period)
    if info.direction == "flat":
        return info, "TREND_FLAT"
    return info, None


def _find_swing_step(
    candles: List[Candle], direction: Direction
) -> Tuple[Optional[Swing], Optional[str]]:
    swing = find_last_swing(candles, direction=direction)
    if swing is None or swing.low >= swing.high:
        return None, "NO_SWING"
    return swing, None


def _check_fibo_step(
    candles: List[Candle], swing: Swing, levels: tuple
) -> Tuple[FiboZoneInfo, Optional[str]]:
    # Fibo retrace math depends on direction.
    trend_dir: Direction = "up"
    try:
        # best-effort: infer from swing direction later; actual direction is passed by caller when available
        trend_dir = "up"
    except Exception:
        trend_dir = "up"

    info = check_fibo_retrace_zone(candles, swing, levels, direction=trend_dir)
    if not info.in_zone:
        return info, f"FIBO_FAIL|{info.zone_low:.4f}-{info.zone_high:.4f}|Last:{info.last_close:.4f}"
    return info, None


def _check_fibo_step_dir(
    candles: List[Candle], swing: Swing, levels: tuple, direction: Direction
) -> Tuple[FiboZoneInfo, Optional[str]]:
    info = check_fibo_retrace_zone(candles, swing, levels, direction=direction)
    if not info.in_zone:
        return info, f"FIBO_FAIL|{info.zone_low:.4f}-{info.zone_high:.4f}|Last:{info.last_close:.4f}"
    return info, None


# --- Main Core Function (Pure) ---

def scan_pair_cached(
    pair: str,
    profile: Dict[str, Any],
    trend_candles: List[Candle],
    entry_candles: List[Candle]
) -> ScanResult:
    """
    NEW PIPELINE ARCHITECTURE:
    1. Detect trend
    2. Compute primitives (once)
    3. Run all enabled detectors
    4. Score and rank signals
    5. Return best signal
    """
    reasons: List[str] = []
    debug: Dict[str, Any] = {}

    try:
        strategy_id = str(profile.get("strategy_id") or "").strip() or None
        if strategy_id:
            debug["strategy_id"] = strategy_id
    except Exception:
        pass
    
    trend_tf = str(profile.get("trend_tf", "H4")).upper()
    entry_tf = str(profile.get("entry_tf", "M15")).upper()
    strategy_name = str(profile.get("name") or "").strip() or None
    
    # Config extraction
    blocks = profile.get("blocks", {})
    blocks = blocks if isinstance(blocks, dict) else {}
    trend_cfg = (blocks.get("trend", {}) or {}) if isinstance(blocks.get("trend", {}), dict) else {}
    
    ma_period = int(trend_cfg.get("ma_period", 50))
    min_rr = float(profile.get("min_rr", 3.0))
    
    # 1. Validate data sufficiency
    err_suff = _validate_data_sufficiency(trend_candles, entry_candles, ma_period)
    if err_suff:
        reasons.append(err_suff)
        return ScanResult(pair, False, None, reasons, trend_tf=trend_tf, entry_tf=entry_tf, strategy_name=strategy_name, debug=debug)
    
    # 2. Detect trend
    trend_info, err_trend = _analyze_trend_step(trend_candles, ma_period)
    if err_trend:
        reasons.append(err_trend)
        return ScanResult(
            pair, False, None, reasons,
            trend_info=trend_info,
            trend_tf=trend_tf, entry_tf=entry_tf,
            strategy_name=strategy_name,
            debug=debug,
        )
    
    # 3. Compute primitives ONCE
    try:
        t_feat = time.perf_counter()
        primitives = compute_primitives(
            trend_candles=trend_candles,
            entry_candles=entry_candles,
            trend_direction=trend_info.direction,
            config=blocks,
        )
        debug["feature_build_ms"] = (time.perf_counter() - t_feat) * 1000.0
    except Exception as e:
        reasons.append(f"PRIMITIVE_ERROR|{str(e)}")
        return ScanResult(pair, False, None, reasons, trend_tf=trend_tf, entry_tf=entry_tf, debug=debug)
    
    # 4. Get enabled detectors
    detector_configs = profile.get("detectors", {})
    detectors = get_enabled_detectors(detector_configs, default_enabled=["trend_fibo"])
    
    if not detectors:
        reasons.append("NO_ENABLED_DETECTORS")
        return ScanResult(pair, False, None, reasons, trend_tf=trend_tf, entry_tf=entry_tf)
    
    # 5. Run all enabled detectors
    signals: List[DetectorSignal] = []
    annotations: List[DetectorSignal] = []
    per_detector_ms: Dict[str, float] = {}
    t_det_total = time.perf_counter()
    for detector_name, detector in detectors.items():
        try:
            t_det = time.perf_counter()
            signal = detector.detect(
                pair=pair,
                entry_candles=entry_candles,
                trend_candles=trend_candles,
                primitives=primitives,
                user_config=profile,
            )
            per_detector_ms[detector_name] = (time.perf_counter() - t_det) * 1000.0
            if signal:
                if getattr(signal, "kind", "signal") == "annotation":
                    annotations.append(signal)
                else:
                    signals.append(signal)
        except Exception as e:
            reasons.append(f"DETECTOR_ERROR|{detector_name}|{str(e)}")

    debug["detectors_total_ms"] = (time.perf_counter() - t_det_total) * 1000.0
    debug["per_detector_ms"] = per_detector_ms
    
    # 6. Score and rank signals
    if not signals:
        reasons.append("NO_SIGNALS_FROM_DETECTORS")
        return ScanResult(pair, False, None, reasons, trend_tf=trend_tf, entry_tf=entry_tf)
    
    t_score = time.perf_counter()
    ranked = score_and_rank_signals(signals, min_rr=min_rr)
    debug["scoring_ms"] = (time.perf_counter() - t_score) * 1000.0
    
    if not ranked:
        reasons.append("ALL_SIGNALS_FILTERED_BY_RR")
        return ScanResult(pair, False, None, reasons, trend_tf=trend_tf, entry_tf=entry_tf)
    
    # 7. Take best signal and convert to Setup format
    best_signal = ranked[0].signal
    
    # Convert DetectorSignal to Setup for backward compatibility
    setup = Setup(
        pair=best_signal.pair,
        direction=best_signal.direction,
        entry=best_signal.entry,
        sl=best_signal.sl,
        tp=best_signal.tp,
        rr=best_signal.rr,
        trend_info=trend_info,
        fibo_info=None,  # Not all detectors use fibo
    )
    
    reasons.extend(best_signal.reasons)
    # Add warnings/annotations at the end so they don't mask primary reasons
    for ann in annotations:
        for r in ann.reasons:
            reasons.append(f"WARN|{ann.detector_name}|{r}")
    reasons.append(f"DETECTOR|{best_signal.detector_name}")
    reasons.append(f"SCORE|{ranked[0].score:.2f}")
    
    return ScanResult(
        pair, True, setup, reasons,
        trend_info=trend_info,
        trend_tf=trend_tf,
        entry_tf=entry_tf,
        strategy_name=strategy_name,
        debug=debug,
    )


def scan_pair_cached_indicator_free(
    pair: str,
    profile: Dict[str, Any],
    trend_candles: List[Candle],
    entry_candles: List[Candle],
) -> ScanResult:
    """
    NEW INDICATOR-FREE ENGINE PIPELINE.
    
    Uses structure-based trend detection (HH/HL vs LH/LL) instead of MA.
    Runs detector plugins for signal generation.
    
    Flow:
    1. Compute primitives (including structure trend)
    2. Detect trend from structure (not MA)
    3. Run enabled detectors
    4. Score and filter signals
    5. Build setup from best signal
    
    Args:
        pair: Trading pair (e.g., "EURUSD")
        profile: User profile with detectors config
        trend_candles: Higher TF candles for trend
        entry_candles: Lower TF candles for entry
        
    Returns:
        ScanResult with setup or reasons for no setup
    """
    from core.primitives import compute_primitives
    from engines.detectors import detector_registry
    from build_basic_setup_v2 import BuildSetupResult, build_basic_setup_v2
    import config as app_config
    import os

    # Reuse global _coerce_bool
    
    trend_tf = profile.get("trend_tf", "H4")
    entry_tf = profile.get("entry_tf", "M15")
    min_rr = profile.get("min_rr", 2.0)
    
    reasons: List[str] = []
    debug: Dict[str, Any] = {}

    from core.feature_flags import FeatureFlags, canary_detector_list

    flags = FeatureFlags.from_sources(config=profile.get("feature_flags"))
    shadow_all = bool(flags.shadow_all_detectors)
    if shadow_all:
        debug["shadow_enabled"] = True

    if flags.canary_mode:
        debug["canary_mode"] = True

    # Record flags snapshot for ops/debug (non-breaking: additive key).
    debug["feature_flags"] = flags.as_dict()

    canary_detectors = canary_detector_list(config=profile)

    try:
        strategy_id = str(profile.get("strategy_id") or "").strip() or None
        if strategy_id:
            debug["strategy_id"] = strategy_id
    except Exception:
        pass
    
    # Validate data
    import config as _config
    _min_trend = int(getattr(_config, 'MIN_TREND_BARS', 45) or 45)
    if len(trend_candles) < _min_trend:
        return ScanResult(
            pair, False, None,
            [f"Trend data insufficient: {len(trend_candles)} < {_min_trend}"],
            trend_tf=trend_tf,
            entry_tf=entry_tf,
        )
    
    if len(entry_candles) < 20:
        return ScanResult(
            pair, False, None,
            [f"Entry data insufficient: {len(entry_candles)} < 20"],
            trend_tf=trend_tf,
            entry_tf=entry_tf,
        )
    
    # 1. Compute primitives (includes structure trend)
    try:
        t_feat = time.perf_counter()
        primitives = compute_primitives(
            trend_candles=trend_candles,
            entry_candles=entry_candles,
            trend_direction="flat",  # Will be determined by structure
            config=profile.get("primitives_config", {}),
        )
        debug["feature_build_ms"] = (time.perf_counter() - t_feat) * 1000.0
    except Exception as e:
        return ScanResult(
            pair, False, None,
            [f"Primitives computation failed: {str(e)}"],
            trend_tf=trend_tf,
            entry_tf=entry_tf,
            debug=debug,
        )
    
    # 2. Detect trend from structure (indicator-free!)
    require_clear_trend = _coerce_bool(
        profile.get("require_clear_trend_for_signal"),
        bool(getattr(app_config, "REQUIRE_CLEAR_TREND_FOR_SIGNAL", False)),
    )

    from core.primitives import analyze_structure

    struct = primitives.structure_trend
    structure_result = analyze_structure(entry_candles=entry_candles, structure_trend=struct)
    regime = str(structure_result.regime)
    regime_evidence: Dict[str, Any] = dict(structure_result.evidence or {})

    trend_direction = str(getattr(struct, "direction", "flat") if struct else "flat")
    has_clear_trend = bool(regime in ("TREND_BULL", "TREND_BEAR"))

    # --- Regime classification (always returns a regime) ---
    # TREND_BULL / TREND_BEAR / RANGE / CHOP
    if has_clear_trend:
        # Keep direction logging for existing UX/tests.
        reasons.append(f"STRUCTURE_TREND|{trend_direction.upper()}")
        if struct is not None:
            reasons.append(f"HH={struct.hh_count}")
            reasons.append(f"HL={struct.hl_count}")
            reasons.append(f"LH={struct.lh_count}")
            reasons.append(f"LL={struct.ll_count}")
    else:
        # Don't hard-fail: treat as range/chop.
        reasons.append("TREND_UNCLEAR_REGIME_FALLBACK")
        if struct is not None:
            reasons.append(f"HH={int(getattr(struct, 'hh_count', 0))}")
            reasons.append(f"HL={int(getattr(struct, 'hl_count', 0))}")
            reasons.append(f"LH={int(getattr(struct, 'lh_count', 0))}")
            reasons.append(f"LL={int(getattr(struct, 'll_count', 0))}")

        if require_clear_trend:
            reasons.append(f"REGIME|{regime}")
            debug["regime"] = regime
            if regime_evidence:
                debug["regime_evidence"] = regime_evidence
            return ScanResult(
                pair,
                False,
                None,
                reasons,
                trend_tf=trend_tf,
                entry_tf=entry_tf,
                debug=debug,
            )

    reasons.append(f"REGIME|{regime}")
    debug["regime"] = regime
    if regime_evidence:
        debug["regime_evidence"] = regime_evidence

    from engine.models import DetectorHit
    from scoring.soft_combine import combine
    from strategies.loader import load_strategies_from_profile
    from strategies.strategy_spec import StrategySpec

    default_allow_list = [
        "structure_trend",
        "sr_bounce",
        "fibo_retrace",
        "fakeout_trap",
        "range_box_edge",
    ]

    # Build active strategies from profile (never raises)
    active_specs: List[StrategySpec] = []
    try:
        load_res = load_strategies_from_profile(profile)
        for raw in (load_res.strategies or []):
            if not isinstance(raw, dict):
                continue
            # Backward-compat: profiles without StrategySpec fields should not
            # suddenly become stricter due to StrategySpec defaults.
            raw2 = dict(raw)
            if raw2.get("min_score") is None:
                try:
                    raw2["min_score"] = float(profile.get("min_score") or 0.0)
                except Exception:
                    raw2["min_score"] = 0.0
            if raw2.get("min_rr") is None:
                try:
                    raw2["min_rr"] = float(profile.get("min_rr") or 2.0)
                except Exception:
                    raw2["min_rr"] = 2.0
            spec, errs = StrategySpec.from_dict(raw2)
            if spec is None or errs:
                continue
            if not spec.enabled:
                continue
            active_specs.append(spec)
    except Exception:
        active_specs = []

    if not active_specs:
        # Backward-compatible fallback: treat profile-level config as one strategy.
        # Many tests/legacy callers pass only {detectors, allowed_regimes, min_score, ...}
        # without StrategySpec fields (notably strategy_id).
        raw_profile = profile if isinstance(profile, dict) else {}
        has_strategy_like_fields = any(
            k in raw_profile
            for k in (
                "detectors",
                "allowed_regimes",
                "detector_params",
                "family_params",
                "detector_weights",
                "family_weights",
                "weights",
            )
        )
        if has_strategy_like_fields:
            raw0 = dict(raw_profile)
            raw0.setdefault("strategy_id", "profile_default")
            raw0.setdefault("enabled", True)

            if raw0.get("priority") is None:
                try:
                    raw0["priority"] = int(raw_profile.get("priority") or 100)
                except Exception:
                    raw0["priority"] = 100

            # Important: default min_score to 0.0 for backward compatibility.
            if raw0.get("min_score") is None:
                try:
                    raw0["min_score"] = float(raw_profile.get("min_score") or 0.0)
                except Exception:
                    raw0["min_score"] = 0.0

            if raw0.get("min_rr") is None:
                try:
                    raw0["min_rr"] = float(raw_profile.get("min_rr") or 2.0)
                except Exception:
                    raw0["min_rr"] = 2.0

            spec0, errs0 = StrategySpec.from_dict(raw0)
            if spec0 is not None and not errs0:
                active_specs = [spec0]

    best_fail_debug: Dict[str, Any] = dict(debug)
    best_fail_reason: Optional[str] = None
    best_fail_score: float = float("-inf")

    attempted_strategies = 0
    blocked_strategies = 0

    strategy_skips: List[Dict[str, Any]] = []

    # Successful candidates for arbitration (v1).
    candidates: List[Dict[str, Any]] = []

    def _record_failure(reason: str, dbg: Dict[str, Any], *, score: float = 0.0) -> None:
        nonlocal best_fail_reason, best_fail_debug, best_fail_score
        try:
            s = float(score)
        except Exception:
            s = 0.0
        if best_fail_reason is None or s > best_fail_score:
            best_fail_reason = str(reason)
            best_fail_score = float(s)
            best_fail_debug = dict(dbg)

    # Apply a small penalty in RANGE/CHOP (less conviction).
    regime_penalty = 0.05 if regime in ("RANGE", "CHOP") else 0.0
    if regime_penalty:
        debug["regime_score_penalty"] = regime_penalty

    for spec in active_specs:
        # Strategy regime filter
        allowed = [str(x).strip().upper() for x in (spec.allowed_regimes or []) if str(x).strip()]
        if allowed and str(regime) not in set(allowed):
            blocked_strategies += 1
            # v1: don't emit PAIR_NONE for this; just skip.
            # Keep lightweight debug evidence in case another strategy hits.
            if len(strategy_skips) < 8:
                strategy_skips.append({"strategy_id": spec.strategy_id, "reason": "REGIME_BLOCKED"})
            continue

        attempted_strategies += 1

        allow_list = list(spec.detectors) if spec.detectors else list(default_allow_list)

        all_names: List[str] = []
        if shadow_all:
            try:
                all_names = list(detector_registry.list_detectors() or [])
            except Exception:
                all_names = []

        # Build effective detector params/configs.
        # Merge order: base defaults < family_params[family] < detector_params[detector]
        detector_params_raw: Dict[str, Any] = {}
        family_params_raw: Dict[str, Any] = {}
        try:
            detector_params_raw = dict(getattr(spec, "detector_params", {}) or {})
        except Exception:
            detector_params_raw = {}
        try:
            family_params_raw = dict(getattr(spec, "family_params", {}) or {})
        except Exception:
            family_params_raw = {}

        effective_params_by_detector: Dict[str, Dict[str, Any]] = {}
        detector_configs: Dict[str, Dict[str, Any]] = {}
        truncated_detectors: List[str] = []

        for name in allow_list:
            family = "misc"
            try:
                cls = detector_registry.get_detector_class(name)
                if cls is not None:
                    if "meta" in getattr(cls, "__dict__", {}):
                        family = str(getattr(getattr(cls, "meta", None), "family", "misc") or "misc")
                    elif "family" in getattr(cls, "__dict__", {}):
                        family = str(getattr(cls, "family", "misc") or "misc")
                    else:
                        family = str(getattr(cls, "family", "misc") or "misc")
            except Exception:
                family = "misc"

            fam_params = {}
            det_params = {}
            try:
                v = family_params_raw.get(family)
                if isinstance(v, dict):
                    fam_params = dict(v)
            except Exception:
                fam_params = {}
            try:
                v2 = detector_params_raw.get(name)
                if isinstance(v2, dict):
                    det_params = dict(v2)
            except Exception:
                det_params = {}

            merged_params = merge_param_layers(base={}, family=fam_params, detector=det_params)
            merged_params_s, trunc = sanitize_params(merged_params)
            if trunc:
                truncated_detectors.append(str(name))

            merged_params_s = merged_params_s if isinstance(merged_params_s, dict) else {}
            effective_params_by_detector[str(name)] = dict(merged_params_s)

            cfg = {"enabled": True}
            cfg.update(dict(merged_params_s))
            detector_configs[str(name)] = cfg

        # Shadow coverage: build configs for ALL detectors (coverage only).
        shadow_detector_configs: Dict[str, Dict[str, Any]] = {}
        if shadow_all and all_names:
            for name in all_names:
                family = "misc"
                try:
                    cls = detector_registry.get_detector_class(name)
                    if cls is not None:
                        if "meta" in getattr(cls, "__dict__", {}):
                            family = str(getattr(getattr(cls, "meta", None), "family", "misc") or "misc")
                        elif "family" in getattr(cls, "__dict__", {}):
                            family = str(getattr(cls, "family", "misc") or "misc")
                        else:
                            family = str(getattr(cls, "family", "misc") or "misc")
                except Exception:
                    family = "misc"

                fam_params = {}
                det_params = {}
                try:
                    v = family_params_raw.get(family)
                    if isinstance(v, dict):
                        fam_params = dict(v)
                except Exception:
                    fam_params = {}
                try:
                    v2 = detector_params_raw.get(name)
                    if isinstance(v2, dict):
                        det_params = dict(v2)
                except Exception:
                    det_params = {}

                merged_params = merge_param_layers(base={}, family=fam_params, detector=det_params)
                merged_params_s, _ = sanitize_params(merged_params)
                merged_params_s = merged_params_s if isinstance(merged_params_s, dict) else {}

                cfg = {"enabled": True}
                cfg.update(dict(merged_params_s))
                shadow_detector_configs[str(name)] = cfg

        params_digest = stable_params_digest(effective_params_by_detector)

        debug_s: Dict[str, Any] = dict(debug)
        debug_s["strategy_id"] = spec.strategy_id
        debug_s["allowed_regimes"] = list(allowed) if allowed else list(spec.allowed_regimes)
        debug_s["min_score"] = float(spec.min_score)
        debug_s["min_rr"] = float(spec.min_rr)
        debug_s["params_digest"] = params_digest
        if truncated_detectors:
            debug_s["params_truncated_detectors"] = sorted(set(truncated_detectors))
        if strategy_skips:
            debug_s["strategy_skips"] = list(strategy_skips)

        # Keep call signature compatible with tests that monkeypatch load_from_profile.
        # Flags are still applied via profile['feature_flags'] inside the registry.
        detectors = detector_registry.load_from_profile(
            {"detectors": detector_configs, "feature_flags": profile.get("feature_flags")}
        )

        shadow_hits: List[str] = []
        shadow_errors: List[str] = []
        shadow_total_eligible = 0
        if shadow_all and shadow_detector_configs:
            try:
                shadow_detectors = detector_registry.load_from_profile(
                    {"detectors": shadow_detector_configs, "feature_flags": profile.get("feature_flags")}
                )

                # Filter by supported regime
                eligible_shadow = []
                for d in shadow_detectors:
                    try:
                        supported = set(getattr(getattr(d, "meta", None), "supported_regimes", set()) or set())
                        if supported and str(regime) not in supported:
                            continue
                    except Exception:
                        pass
                    eligible_shadow.append(d)

                shadow_total_eligible = int(len(eligible_shadow))
                for d in eligible_shadow:
                    if not d.is_enabled():
                        continue
                    try:
                        from engines.detectors.runner import safe_detect

                        r, _ms = safe_detect(
                            d,
                            candles=entry_candles,
                            primitives=primitives,
                            context={"pair": pair, "strategy_id": spec.strategy_id, "shadow": True},
                            logger=None,
                            scan_id=str(debug_s.get("scan_id") or "NA"),
                            flags=flags,
                        )
                        if getattr(r, "match", False):
                            shadow_hits.append(str(d.get_name()))
                    except Exception:
                        shadow_errors.append(str(d.get_name()))
            except Exception:
                shadow_hits = []
                shadow_errors = []
                shadow_total_eligible = 0

        # Filter by supported regime
        eligible = []
        skipped = []
        for d in detectors:
            try:
                supported = set(getattr(getattr(d, "meta", None), "supported_regimes", set()) or set())
                if supported and str(regime) not in supported:
                    skipped.append(d.get_name())
                    continue
            except Exception:
                pass
            eligible.append(d)
        detectors = eligible
        if skipped:
            debug_s["detectors_skipped_regime"] = sorted(set(skipped))
        debug_s["detectors_considered"] = sorted({d.get_name() for d in detectors})
        # Required: detectors_total must reflect eligible detectors count.
        debug_s["detectors_total"] = int(len(detectors))

        if shadow_all:
            uniq_hits = sorted(set([h for h in shadow_hits if h]))
            debug_s["shadow_detectors_total"] = int(shadow_total_eligible)
            debug_s["shadow_hit_count"] = int(len(uniq_hits))
            debug_s["shadow_hits"] = uniq_hits
            debug_s["shadow_errors_count"] = int(len(shadow_errors))
            if shadow_errors:
                debug_s["shadow_errors"] = shadow_errors[:5]

        # Debug-only: params used (sanitized & bounded).
        try:
            used_map = {k: effective_params_by_detector.get(k, {}) for k in debug_s["detectors_considered"]}
            debug_s["detector_params_used"] = used_map
        except Exception:
            pass

        if not detectors:
            # Track best failure evidence
            _record_failure("NO_DETECTORS_FOR_REGIME", debug_s, score=0.0)
            continue

        # Run detectors (safe, contract-enforced)
        context = {
            "pair": pair,
            "trend_tf": trend_tf,
            "entry_tf": entry_tf,
            "user_profile": profile,
            "strategy_id": spec.strategy_id,
        }

        per_detector_ms: Dict[str, float] = {}
        detector_results = []
        t_det_total = time.perf_counter()
        for det in detectors:
            if not det.is_enabled():
                continue
            from engines.detectors.runner import safe_detect

            r, ms = safe_detect(
                det,
                candles=entry_candles,
                primitives=primitives,
                context=context,
                logger=None,
                scan_id=str(debug_s.get("scan_id") or "NA"),
                flags=flags,
            )
            per_detector_ms[det.get_name()] = float(ms)
            if getattr(r, "match", False):
                detector_results.append(r)
        debug_s["detectors_total_ms"] = (time.perf_counter() - t_det_total) * 1000.0
        debug_s["per_detector_ms"] = per_detector_ms

        # Canary mode: run selected detectors in shadow and compare hits.
        if flags.canary_mode and canary_detectors:
            canary_hits: List[str] = []
            canary_errors: List[str] = []
            baseline_hits = sorted({str(getattr(r, "detector_name", "") or "") for r in detector_results if getattr(r, "match", False)})
            try:
                # Run canary detectors even if their own feature_flag isn't enabled.
                canary_cfg = {str(n): {"enabled": True} for n in canary_detectors}
                canary_instances = detector_registry.load_from_profile({"detectors": canary_cfg})
                for d in canary_instances:
                    from engines.detectors.runner import safe_detect

                    try:
                        r2, _ms2 = safe_detect(
                            d,
                            candles=entry_candles,
                            primitives=primitives,
                            context={**context, "shadow": True, "canary": True},
                            logger=None,
                            scan_id=str(debug_s.get("scan_id") or "NA"),
                            flags=flags,
                        )
                        if getattr(r2, "match", False):
                            canary_hits.append(str(d.get_name()))
                    except Exception:
                        canary_errors.append(str(d.get_name()))
            except Exception:
                canary_hits = []
                canary_errors = []

            uniq_canary = sorted(set([h for h in canary_hits if h]))
            new_hits = sorted([h for h in uniq_canary if h not in set(baseline_hits)])
            debug_s["canary_detectors"] = list(canary_detectors)
            debug_s["canary_hit_count"] = int(len(uniq_canary))
            debug_s["canary_hits"] = uniq_canary
            debug_s["canary_new_hits"] = new_hits
            debug_s["canary_errors_count"] = int(len(canary_errors))
            if canary_errors:
                debug_s["canary_errors"] = canary_errors[:5]

        if not detector_results:
            _record_failure("NO_HITS", debug_s, score=0.0)
            continue

        # 4) Soft-combine for this strategy
        t_score = time.perf_counter()
        hits: List[DetectorHit] = []
        hits_debug: List[Dict[str, Any]] = []

        for r in detector_results:
            ddir = getattr(r, "direction", None)
            if ddir not in ("BUY", "SELL"):
                continue

            contrib = getattr(r, "score_contrib", None)
            try:
                contrib_f = float(contrib) if contrib is not None else float(getattr(r, "confidence", 0.0))
            except Exception:
                contrib_f = float(getattr(r, "confidence", 0.0))

            contrib_f = max(0.0, contrib_f - float(regime_penalty))

            tags: List[str] = []
            try:
                tags = [str(t) for t in (list(getattr(r, "tags", []) or []))]
            except Exception:
                tags = []

            family = None
            try:
                det_obj = next((d for d in detectors if d.get_name() == r.detector_name), None)
                if det_obj is not None:
                    family = str(det_obj.get_family())
            except Exception:
                family = None

            evidence_dict: Dict[str, Any] = {}
            try:
                evidence_dict = dict(getattr(r, "evidence_dict", {}) or {})
            except Exception:
                evidence_dict = {}
            if tags:
                evidence_dict["tags"] = list(tags)
            if family:
                evidence_dict["family"] = family

                # Param snapshot for reproducibility (sanitized & bounded)
                try:
                    p = effective_params_by_detector.get(str(r.detector_name), {})
                    evidence_dict["params"], _ = sanitize_params(p)
                except Exception:
                    pass

            reasons_list: List[str] = []
            try:
                reasons_list = [
                    str(x)
                    for x in (
                        list(getattr(r, "reasons", []) or [])
                        or list(getattr(r, "evidence", []) or [])
                    )
                ]
            except Exception:
                reasons_list = []

            hits.append(
                DetectorHit(
                    detector=str(r.detector_name),
                    direction=ddir,
                    score_contrib=float(contrib_f),
                    family=str(family or ""),
                    reasons=reasons_list,
                    evidence=evidence_dict,
                )
            )
            hits_debug.append(
                {
                    "detector": str(r.detector_name),
                    "dir": str(ddir),
                    "score_contrib": float(contrib_f),
                    "tags": list(tags),
                    "family": family,
                }
            )

        comb = combine(hits, spec, regime)
        debug_s["soft_scores"] = {
            "buy": float(comb.evidence.get("buy_score", 0.0) or 0.0),
            "sell": float(comb.evidence.get("sell_score", 0.0) or 0.0),
            "min_score": float(spec.min_score),
            "epsilon": float(spec.conflict_epsilon),
            "family_bonus": float(spec.confluence_bonus_per_family),
        }
        try:
            if isinstance(comb.evidence.get("score_breakdown"), dict):
                debug_s["score_breakdown"] = dict(comb.evidence.get("score_breakdown") or {})
        except Exception:
            pass
        debug_s["hits"] = hits_debug
        debug_s["scoring_ms"] = (time.perf_counter() - t_score) * 1000.0
        debug_s["score"] = float(comb.evidence.get("score", comb.score) or 0.0)
        debug_s["buy_score"] = float(comb.evidence.get("buy_score", 0.0) or 0.0)
        debug_s["sell_score"] = float(comb.evidence.get("sell_score", 0.0) or 0.0)
        debug_s["min_score"] = float(spec.min_score)
        debug_s["detectors_hit"] = list(comb.evidence.get("detectors_hit") or [])

        # Attach conflict evidence for QA and ops visibility
        try:
            conflict_delta = comb.evidence.get("conflict_delta")
            if conflict_delta is not None:
                debug_s["conflict"] = {
                    "delta": float(conflict_delta),
                    "epsilon": float(spec.conflict_epsilon),
                }
        except Exception:
            pass

        if not comb.ok:
            fr = str(comb.fail_reason or "SCORE_FAILED")
            if fr == "SCORE_BELOW_MIN":
                fr = f"SCORE_BELOW_MIN|{float(comb.score):.2f}<{float(spec.min_score):.2f}"

            try:
                s_val = float(comb.score)
            except Exception:
                s_val = 0.0
            _record_failure(fr, debug_s, score=s_val)
            continue

        chosen_dir = str(comb.direction)
        chosen_score = float(comb.score)
        hits_for_dir = [r for r in detector_results if getattr(r, "direction", None) == chosen_dir]
        if not hits_for_dir:
            _record_failure("NO_HITS", debug_s, score=0.0)
            continue

        def _hit_contrib(x: Any) -> float:
            try:
                return float(getattr(x, "score_contrib", None) or getattr(x, "confidence", 0.0))
            except Exception:
                return 0.0

        hits_for_dir.sort(key=_hit_contrib, reverse=True)
        best_result = hits_for_dir[0]

        reasons_s = list(reasons)
        reasons_s.append(f"DETECTOR|{best_result.detector_name}")
        reasons_s.append(f"SCORE|{chosen_score:.2f}")
        reasons_s.append(f"MIN_SCORE|{float(spec.min_score):.2f}")
        reasons_s.append(f"DETECTORS_HIT|{len(hits_for_dir)}")
        try:
            for rr0 in list(getattr(best_result, "reasons", []) or getattr(best_result, "evidence", []) or [])[:4]:
                reasons_s.append(str(rr0))
        except Exception:
            pass

        # 5) Build setup
        last_close = entry_candles[-1].close
        min_rr_s = float(spec.min_rr)

        if best_result.entry and best_result.sl and best_result.tp:
            entry_price = float(best_result.entry)
            sl_price = float(best_result.sl)
            tp_price = float(best_result.tp)

            sl_dist = abs(float(entry_price) - float(sl_price))
            tp_dist = abs(float(tp_price) - float(entry_price))
            rr_calc = float(tp_dist / sl_dist) if sl_dist > 0 else 0.0
            rr = float(best_result.rr) if best_result.rr is not None else rr_calc
            if rr <= 0:
                rr = rr_calc

            debug_s["setup_evidence"] = {
                "entry": float(entry_price),
                "sl": float(sl_price),
                "tp": float(tp_price),
                "sl_dist": float(sl_dist),
                "tp_dist": float(tp_dist),
                "rr": float(rr),
                "min_rr": float(min_rr_s),
                "source": "detector",
            }
        else:
            try:
                bs: BuildSetupResult = build_basic_setup_v2(
                    pair=pair,
                    direction=best_result.direction,
                    entry_price=last_close,
                    primitives=primitives,
                    min_rr=min_rr_s,
                    profile=profile,
                )

                if not bs.ok or bs.setup is None:
                    if isinstance(bs.evidence, dict):
                        debug_s["setup_fail"] = bs.evidence
                    # Try next strategy
                    continue

                entry_price = float(bs.setup.entry)
                sl_price = float(bs.setup.sl)
                tp_price = float(bs.setup.tp)
                rr = float(bs.setup.rr)
                debug_s["setup_ok"] = bool(bs.ok)
                if isinstance(bs.evidence, dict):
                    debug_s["setup_evidence"] = bs.evidence

            except Exception:
                continue

        if rr < min_rr_s:
            # Try next strategy
            continue

        reasons_s.append(f"RR|{rr:.2f}")

        setup = Setup(
            pair=pair,
            direction=best_result.direction,
            entry=entry_price,
            sl=sl_price,
            tp=tp_price,
            rr=rr,
            trend_info=None,
            fibo_info=None,
        )

        # Store candidate for arbitration.
        debug_s["strategy_id"] = spec.strategy_id
        candidate_result = ScanResult(
            pair,
            True,
            setup,
            reasons_s,
            trend_info=None,
            trend_tf=trend_tf,
            entry_tf=entry_tf,
            strategy_name="indicator_free_v1",
            debug=debug_s,
        )
        candidates.append(
            {
                "strategy_id": str(spec.strategy_id),
                "score": float(chosen_score),
                "priority": int(getattr(spec, "priority", 100)),
                "rr": float(rr),
                "result": candidate_result,
            }
        )

    if candidates:
        from strategies.arbitration import StrategyCandidate, select_winner

        def _cand_key(c: Dict[str, Any]):
            try:
                score_v = float(c.get("score") or 0.0)
            except Exception:
                score_v = 0.0
            try:
                prio_v = int(c.get("priority") if c.get("priority") is not None else 100)
            except Exception:
                prio_v = 100
            try:
                rr_v = float(c.get("rr") or 0.0)
            except Exception:
                rr_v = 0.0
            return (score_v, -prio_v, rr_v)

        winner_obj = select_winner(
            [
                StrategyCandidate(
                    strategy_id=str(c.get("strategy_id")),
                    score=float(c.get("score") or 0.0),
                    priority=int(c.get("priority") if c.get("priority") is not None else 100),
                    rr=float(c.get("rr") or 0.0),
                )
                for c in candidates
            ]
        )
        winner = None
        if winner_obj is not None:
            winner = next((c for c in candidates if str(c.get("strategy_id")) == winner_obj.strategy_id), None)
        if winner is None:
            winner = max(candidates, key=_cand_key)

        # candidates_sorted: selection order (score, -priority, rr)
        candidates_sorted = sorted(candidates, key=_cand_key, reverse=True)

        # candidates_top: score-desc only (stable for ops readability)
        candidates_by_score = sorted(
            candidates,
            key=lambda c: float(c.get("score") or 0.0) if isinstance(c, dict) else 0.0,
            reverse=True,
        )
        top_pairs = []
        for c in candidates_by_score[:5]:
            try:
                top_pairs.append(f"{str(c.get('strategy_id'))}:{float(c.get('score') or 0.0):.2f}")
            except Exception:
                top_pairs.append(f"{str(c.get('strategy_id'))}:0.00")

        # Ranked candidates for downstream governance failover.
        ranked_meta: List[Dict[str, Any]] = []
        ranked_results: List[ScanResult] = []
        for c in candidates_sorted:
            try:
                r = c.get("result") if isinstance(c, dict) else None
                if isinstance(r, ScanResult):
                    ranked_results.append(r)
                ranked_meta.append(
                    {
                        "strategy_id": str(c.get("strategy_id")),
                        "score": float(c.get("score") or 0.0),
                        "priority": int(c.get("priority") if c.get("priority") is not None else 100),
                        "rr": float(c.get("rr") or 0.0),
                        "direction": (r.setup.direction if isinstance(r, ScanResult) and r.setup is not None else None),
                    }
                )
            except Exception:
                continue

        winner_result = winner.get("result") if isinstance(winner, dict) else None
        if isinstance(winner_result, ScanResult):
            try:
                dbg_w = winner_result.debug if isinstance(winner_result.debug, dict) else {}
                dbg_w = dict(dbg_w)
                dbg_w["candidates"] = int(len(candidates))
                dbg_w["candidates_top"] = ",".join(top_pairs)
                dbg_w["candidates_ranked"] = ranked_meta
                # Private: not for logging (contains python objects)
                dbg_w["_candidates_ranked_results"] = ranked_results
                dbg_w["winner_strategy_id"] = str(winner.get("strategy_id")) if isinstance(winner, dict) else None
                dbg_w["strategy_id"] = str(winner.get("strategy_id")) if isinstance(winner, dict) else dbg_w.get("strategy_id")
                winner_result.debug = dbg_w
            except Exception:
                pass
            return winner_result

    # No strategy produced a setup
    best_fail_debug["candidates"] = 0
    fail_reasons = list(reasons)
    if attempted_strategies == 0 and blocked_strategies > 0:
        fail_reasons.append("REGIME_BLOCKED")
        best_fail_debug["blocked_strategies"] = int(blocked_strategies)
        if strategy_skips:
            best_fail_debug["strategy_skips"] = list(strategy_skips)
    else:
        main_fail = str(best_fail_reason or "NO_HITS")
        # Some failure reasons are expected to be surfaced first.
        # Keep existing regime/context reasons first for most cases.
        if main_fail in ("CONFLICT_SCORE",):
            if main_fail not in fail_reasons:
                fail_reasons = [main_fail] + fail_reasons
        else:
            fail_reasons.append(main_fail)
    return ScanResult(
        pair,
        False,
        None,
        fail_reasons,
        trend_info=None,
        trend_tf=trend_tf,
        entry_tf=entry_tf,
        strategy_name="indicator_free_v1",
        debug=best_fail_debug,
    )
    
    # (unreachable)




def scan_pair_with_profile_verbose(pair: str, profile: Dict[str, Any]) -> ScanResult:
    """
    Fetches data (via market_cache) and runs scan_pair_cached.
    Uses resampled cache for performance.
    """
    from market_data_cache import market_cache
    
    # 3. Convert to Candle objects
    def to_objs(dicts: List[Dict[str, Any]]) -> List[Candle]:
        return [
            Candle(
                time=d["time"],
                open=d["open"],
                high=d["high"],
                low=d["low"],
                close=d["close"]
            )
            for d in dicts
        ]

    # 4. Multi-strategy orchestration (each strategy may specify its own TFs)
    best: Optional[ScanResult] = None
    strategies = extract_strategy_configs(profile)
    for strat in strategies:
        trend_tf = str(strat.get("trend_tf", profile.get("trend_tf", "H4")))
        entry_tf = str(strat.get("entry_tf", profile.get("entry_tf", "M15")))

        # Use resampled cache for performance
        trend_data_dicts = market_cache.get_resampled(pair.upper(), trend_tf)
        entry_data_dicts = market_cache.get_resampled(pair.upper(), entry_tf)

        trend_c = to_objs(trend_data_dicts)
        entry_c = to_objs(entry_data_dicts)

        res = scan_pair_cached(pair, strat, trend_c, entry_c)
        # Attach strategy name if present
        if res.strategy_name is None and isinstance(strat, dict):
            res.strategy_name = str(strat.get("name") or "").strip() or None

        if res.has_setup and res.setup is not None:
            if best is None or (best.setup is None) or (res.setup.rr > best.setup.rr):
                best = res
        else:
            # Keep best "non-setup" result only if nothing better exists
            if best is None:
                best = res

    return best or ScanResult(pair, False, None, ["NO_STRATEGIES"])
