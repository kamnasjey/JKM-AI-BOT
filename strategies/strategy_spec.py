from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


_ALLOWED_REGIMES_DEFAULT = ["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"]


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


def _coerce_float(v: Any, default: float) -> float:
    if v is None:
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


def _coerce_int(v: Any, default: int) -> int:
    if v is None:
        return int(default)
    try:
        return int(v)
    except Exception:
        return int(default)


def _coerce_opt_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str

    enabled: bool = True

    # Lower value => higher priority
    priority: int = 100

    # v1: engine emits a single final signal, but keep this for future multi-signal workflows.
    max_signals_per_scan: int = 1

    # Strategy-scoped governance (optional). None => fall back to global/profile.
    cooldown_minutes: Optional[int] = None
    daily_limit: Optional[int] = None

    min_score: float = 1.0
    min_rr: float = 2.0

    allowed_regimes: List[str] = field(default_factory=lambda: list(_ALLOWED_REGIMES_DEFAULT))

    # Allow-list of detector plugin names.
    detectors: List[str] = field(default_factory=list)

    # Weight overrides.
    detector_weights: Dict[str, float] = field(default_factory=dict)
    family_weights: Dict[str, float] = field(default_factory=dict)

    # Optional detector parameter overrides.
    # detector_params: per detector-name overrides
    # family_params: defaults applied to all detectors in that family
    detector_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    family_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Soft-combine parameters.
    conflict_epsilon: float = 0.05
    confluence_bonus_per_family: float = 0.25

    # For logging/UX: how many top hits to show.
    max_top_hits: int = 3

    def validate(self) -> Tuple[bool, List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        if not isinstance(self.strategy_id, str) or not self.strategy_id.strip():
            errors.append("MISSING_STRATEGY_ID")

        if not isinstance(self.enabled, bool):
            errors.append("BAD_ENABLED")

        if not isinstance(self.priority, int):
            errors.append("BAD_PRIORITY")
        if not isinstance(self.max_signals_per_scan, int):
            errors.append("BAD_MAX_SIGNALS_PER_SCAN")
        if isinstance(self.max_signals_per_scan, int) and int(self.max_signals_per_scan) <= 0:
            errors.append("MAX_SIGNALS_PER_SCAN_NONPOSITIVE")

        if self.cooldown_minutes is not None:
            if not isinstance(self.cooldown_minutes, int):
                errors.append("BAD_COOLDOWN_MINUTES")
            elif int(self.cooldown_minutes) < 0:
                errors.append("COOLDOWN_MINUTES_NEGATIVE")

        if self.daily_limit is not None:
            if not isinstance(self.daily_limit, int):
                errors.append("BAD_DAILY_LIMIT")
            elif int(self.daily_limit) < 0:
                errors.append("DAILY_LIMIT_NEGATIVE")

        for k, v in (
            ("min_score", self.min_score),
            ("min_rr", self.min_rr),
            ("conflict_epsilon", self.conflict_epsilon),
            ("confluence_bonus_per_family", self.confluence_bonus_per_family),
        ):
            try:
                float(v)
            except Exception:
                errors.append(f"BAD_{k.upper()}")

        if float(self.min_score) < 0.0:
            errors.append("MIN_SCORE_NEGATIVE")
        if float(self.min_rr) < 0.0:
            errors.append("MIN_RR_NEGATIVE")
        if float(self.conflict_epsilon) < 0.0:
            errors.append("CONFLICT_EPSILON_NEGATIVE")
        if float(self.confluence_bonus_per_family) < 0.0:
            errors.append("CONFLUENCE_BONUS_NEGATIVE")

        if not isinstance(self.allowed_regimes, list) or not self.allowed_regimes:
            errors.append("BAD_ALLOWED_REGIMES")
        else:
            bad = [r for r in self.allowed_regimes if str(r).strip().upper() not in _ALLOWED_REGIMES_DEFAULT]
            if bad:
                errors.append("UNKNOWN_ALLOWED_REGIMES")

        if not isinstance(self.detectors, list):
            errors.append("BAD_DETECTORS")
        else:
            for d in self.detectors:
                if not isinstance(d, str) or not d.strip():
                    errors.append("BAD_DETECTOR_NAME")
                    break

        if not isinstance(self.detector_weights, dict):
            errors.append("BAD_DETECTOR_WEIGHTS")
        else:
            for k, v in self.detector_weights.items():
                if not isinstance(k, str) or not k.strip():
                    errors.append("BAD_DETECTOR_WEIGHT_KEY")
                    break
                try:
                    float(v)
                except Exception:
                    errors.append("BAD_DETECTOR_WEIGHT_VAL")
                    break

        if not isinstance(self.family_weights, dict):
            errors.append("BAD_FAMILY_WEIGHTS")
        else:
            for k, v in self.family_weights.items():
                if not isinstance(k, str) or not k.strip():
                    errors.append("BAD_FAMILY_WEIGHT_KEY")
                    break
                try:
                    float(v)
                except Exception:
                    errors.append("BAD_FAMILY_WEIGHT_VAL")
                    break

        # Params fields must be dicts, but invalid entries are handled safely by loader/runner.
        if not isinstance(self.detector_params, dict):
            warnings.append("BAD_DETECTOR_PARAMS_SHAPE")
        if not isinstance(self.family_params, dict):
            warnings.append("BAD_FAMILY_PARAMS_SHAPE")

        if not isinstance(self.max_top_hits, int):
            errors.append("BAD_MAX_TOP_HITS")
        elif int(self.max_top_hits) <= 0:
            errors.append("MAX_TOP_HITS_NONPOSITIVE")

        return (not errors), errors, warnings

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> Tuple[Optional["StrategySpec"], List[str]]:
        if not isinstance(raw, dict):
            return None, ["NOT_A_DICT"]

        strategy_id = str(raw.get("strategy_id") or "").strip()
        enabled = _coerce_bool(raw.get("enabled"), True)

        priority = _coerce_int(raw.get("priority"), 100)
        max_signals_per_scan = _coerce_int(raw.get("max_signals_per_scan"), 1)

        cooldown_minutes = _coerce_opt_int(raw.get("cooldown_minutes"))
        daily_limit = _coerce_opt_int(raw.get("daily_limit"))

        min_score = _coerce_float(raw.get("min_score"), 1.0)
        min_rr = _coerce_float(raw.get("min_rr"), 2.0)

        allowed_regimes_raw = raw.get("allowed_regimes")
        if isinstance(allowed_regimes_raw, list) and allowed_regimes_raw:
            allowed_regimes = [str(x).strip().upper() for x in allowed_regimes_raw if str(x).strip()]
        else:
            allowed_regimes = list(_ALLOWED_REGIMES_DEFAULT)

        detectors_raw = raw.get("detectors")
        detectors: List[str] = []
        # Accept list[str] or dict{name: {enabled: bool}} (older internal shape)
        if isinstance(detectors_raw, list):
            detectors = [str(x).strip() for x in detectors_raw if isinstance(x, str) and x.strip()]
        elif isinstance(detectors_raw, dict):
            for k, v in detectors_raw.items():
                name = str(k).strip()
                if not name:
                    continue
                enabled = True
                if isinstance(v, dict) and v.get("enabled") is not None:
                    enabled = _coerce_bool(v.get("enabled"), True)
                elif isinstance(v, bool):
                    enabled = bool(v)
                if enabled:
                    detectors.append(name)

        # Weight overrides: accept canonical keys and legacy aliases.
        detector_weights_raw = raw.get("detector_weights")
        if detector_weights_raw is None:
            detector_weights_raw = raw.get("detector_weight_overrides")
        if detector_weights_raw is None:
            detector_weights_raw = raw.get("weights")
        detector_weights: Dict[str, float] = {}
        if isinstance(detector_weights_raw, dict):
            for k, v in detector_weights_raw.items():
                ks = str(k).strip()
                if not ks:
                    continue
                detector_weights[ks] = _coerce_float(v, 1.0)

        family_weights_raw = raw.get("family_weights")
        family_weights: Dict[str, float] = {}
        if isinstance(family_weights_raw, dict):
            for k, v in family_weights_raw.items():
                ks = str(k).strip()
                if not ks:
                    continue
                family_weights[ks] = _coerce_float(v, 1.0)

        detector_params_raw = raw.get("detector_params")
        detector_params: Dict[str, Dict[str, Any]] = {}
        if isinstance(detector_params_raw, dict):
            for k, v in detector_params_raw.items():
                ks = str(k).strip()
                if not ks:
                    continue
                if isinstance(v, dict):
                    detector_params[ks] = dict(v)

        family_params_raw = raw.get("family_params")
        family_params: Dict[str, Dict[str, Any]] = {}
        if isinstance(family_params_raw, dict):
            for k, v in family_params_raw.items():
                ks = str(k).strip()
                if not ks:
                    continue
                if isinstance(v, dict):
                    family_params[ks] = dict(v)

        conflict_epsilon = _coerce_float(
            raw.get("conflict_epsilon") if raw.get("conflict_epsilon") is not None else raw.get("epsilon"),
            0.05,
        )
        confluence_bonus_per_family = _coerce_float(
            raw.get("confluence_bonus_per_family")
            if raw.get("confluence_bonus_per_family") is not None
            else raw.get("family_bonus"),
            0.25,
        )
        max_top_hits = _coerce_int(raw.get("max_top_hits"), 3)

        spec = StrategySpec(
            strategy_id=strategy_id,
            enabled=enabled,
            priority=int(priority),
            max_signals_per_scan=int(max_signals_per_scan),
            cooldown_minutes=cooldown_minutes,
            daily_limit=daily_limit,
            min_score=float(min_score),
            min_rr=float(min_rr),
            allowed_regimes=allowed_regimes,
            detectors=detectors,
            detector_weights=detector_weights,
            family_weights=family_weights,
            detector_params=detector_params,
            family_params=family_params,
            conflict_epsilon=float(conflict_epsilon),
            confluence_bonus_per_family=float(confluence_bonus_per_family),
            max_top_hits=int(max_top_hits),
        )

        ok, errors, _warnings = spec.validate()
        if not ok:
            return None, errors
        return spec, []

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "strategy_id": self.strategy_id,
            "enabled": bool(self.enabled),
            "priority": int(self.priority),
            "max_signals_per_scan": int(self.max_signals_per_scan),
            "min_score": float(self.min_score),
            "min_rr": float(self.min_rr),
            "allowed_regimes": list(self.allowed_regimes),
            "detectors": list(self.detectors),
            "detector_weights": dict(self.detector_weights),
            "family_weights": dict(self.family_weights),
            "detector_params": dict(self.detector_params),
            "family_params": dict(self.family_params),
            "conflict_epsilon": float(self.conflict_epsilon),
            "confluence_bonus_per_family": float(self.confluence_bonus_per_family),
            "max_top_hits": int(self.max_top_hits),
        }
        if self.cooldown_minutes is not None:
            out["cooldown_minutes"] = int(self.cooldown_minutes)
        if self.daily_limit is not None:
            out["daily_limit"] = int(self.daily_limit)
        return out
