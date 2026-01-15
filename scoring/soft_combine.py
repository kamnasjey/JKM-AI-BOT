"""scoring.soft_combine

Soft combine scoring v1.

- Aggregates per-detector hits into BUY/SELL scores.
- Applies a simple confluence bonus when 2+ independent families agree.
- Applies correlation discount for overlapping detector pairs.
- Resolves conflicts score-aware.

Indicator-free: operates on detector hits only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Set, Tuple, Union

from engine.models import CombineResult, DetectorHit
from strategies.strategy_spec import StrategySpec


_REGIMES = {"TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"}
_FAMILIES = {"range", "sr", "structure", "fibo", "geometry", "time", "pattern", "momentum", "mean_reversion", "gate"}

# Correlation discount: detector pairs that often fire together get discounted.
# Key: frozenset({detector_a, detector_b}), Value: discount factor (0.0 = no discount, 1.0 = full discount)
_CORRELATION_PAIRS: Dict[frozenset, float] = {
    frozenset({"pinbar", "pinbar_at_level"}): 0.4,
    frozenset({"sr_bounce", "sr_breakout"}): 0.3,
    frozenset({"fibo_retracement", "fibo_retrace_confluence"}): 0.5,
    frozenset({"range_box_edge", "sr_bounce"}): 0.25,
    frozenset({"compression_expansion", "momentum_continuation"}): 0.3,
}


def _compute_correlation_discount(detectors_hit: List[str]) -> Tuple[float, Dict[str, float]]:
    """Compute correlation discount for overlapping detector pairs.
    
    Returns:
        (total_discount, per_pair_discounts)
    """
    total_discount = 0.0
    per_pair: Dict[str, float] = {}
    
    det_set = set(detectors_hit)
    for pair, discount in _CORRELATION_PAIRS.items():
        if pair.issubset(det_set):
            pair_key = "|".join(sorted(pair))
            per_pair[pair_key] = discount
            total_discount += discount
    
    return total_discount, per_pair


def _hit_family(hit: DetectorHit) -> Optional[str]:
    """Infer family tag for confluence.

    Priority:
    - evidence['family'] if present
    - evidence['tags'] list if present (first matching known family)
    """
    try:
        fam_direct = getattr(hit, "family", None)
        if isinstance(fam_direct, str) and fam_direct:
            return fam_direct
    except Exception:
        pass
    try:
        fam = hit.evidence.get("family") if isinstance(hit.evidence, dict) else None
        if isinstance(fam, str) and fam:
            return fam
    except Exception:
        pass

    try:
        tags = hit.evidence.get("tags") if isinstance(hit.evidence, dict) else None
        if isinstance(tags, list):
            for t in tags:
                ts = str(t)
                if ts in _FAMILIES:
                    return ts
    except Exception:
        pass

    return None


def combine(
    hits: Sequence[DetectorHit],
    spec: Union[StrategySpec, float],
    regime: Optional[str] = None,
    *,
    # Legacy keyword support (kept to avoid breaking older callers/tests)
    min_score: Optional[float] = None,
    epsilon: float = 0.15,
    family_bonus: float = 0.25,
    detector_weight_overrides: Optional[Dict[str, float]] = None,
    conflict_epsilon: Optional[float] = None,
    confluence_weight: Optional[float] = None,
) -> CombineResult:
    """Combine detector hits into a final direction/score.

    Preferred signature:
        combine(hits, spec: StrategySpec, regime: str)

    Backward compatible:
        combine(hits, min_score: float, regime: str, ...)
    """
    # Backward-compatible call path: combine(hits, min_score, regime, ...)
    if not isinstance(spec, StrategySpec):
        min_score_val = float(min_score) if min_score is not None else float(spec)
        if regime is None:
            raise TypeError("combine() missing required argument: 'regime'")
        eps = float(conflict_epsilon) if conflict_epsilon is not None else float(epsilon)
        conf_bonus = float(confluence_weight) if confluence_weight is not None else float(family_bonus)
        det_weights: Dict[str, float] = {}
        fam_weights: Dict[str, float] = {}
        # Legacy overrides may include family:<fam> or <fam> keys
        if isinstance(detector_weight_overrides, dict):
            for k, v in detector_weight_overrides.items():
                try:
                    det_weights[str(k)] = float(v)
                except Exception:
                    continue
        spec_obj = StrategySpec(
            strategy_id="legacy",
            enabled=True,
            min_score=float(min_score_val),
            min_rr=0.0,
            allowed_regimes=["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"],
            detectors=[],
            detector_weights=det_weights,
            family_weights=fam_weights,
            conflict_epsilon=float(eps),
            confluence_bonus_per_family=float(conf_bonus),
            max_top_hits=3,
        )
        return combine(hits, spec_obj, str(regime))

    spec_obj = spec
    if regime is None:
        raise TypeError("combine() missing required argument: 'regime'")

    regime_s = str(regime)
    if regime_s not in _REGIMES:
        regime_s = "RANGE"

    eps = float(spec_obj.conflict_epsilon)
    fam_bonus = float(spec_obj.confluence_bonus_per_family)
    det_w = dict(spec_obj.detector_weights or {})
    fam_w = dict(spec_obj.family_weights or {})

    by_dir: Dict[str, Dict[str, Any]] = {
        "BUY": {"score": 0.0, "score_raw": 0.0, "families": set(), "hits": [], "contribs": []},
        "SELL": {"score": 0.0, "score_raw": 0.0, "families": set(), "hits": [], "contribs": []},
    }

    for hit in hits:
        if not hit.ok:
            continue
        if hit.direction not in ("BUY", "SELL"):
            continue

        base = float(hit.score_contrib or 0.0)

        fam = _hit_family(hit)

        # Apply weights: detector_weights[detector] * family_weights[family]
        det_mult = 1.0
        fam_mult = 1.0
        try:
            det_mult = float(det_w.get(str(hit.detector), 1.0))
        except Exception:
            det_mult = 1.0
        try:
            if fam:
                fam_mult = float(fam_w.get(str(fam), 1.0))
        except Exception:
            fam_mult = 1.0

        contrib = base * det_mult * fam_mult
        by_dir[hit.direction]["score_raw"] += float(base)
        by_dir[hit.direction]["score"] += float(contrib)
        by_dir[hit.direction]["hits"].append(hit)
        if fam:
            by_dir[hit.direction]["families"].add(str(fam))

        # For breakdown/debugging
        try:
            reasons_short: List[str] = []
            if isinstance(hit.reasons, list):
                reasons_short = [str(x) for x in hit.reasons[:2] if str(x)]
        except Exception:
            reasons_short = []
        by_dir[hit.direction]["contribs"].append(
            {
                "detector": str(hit.detector),
                "family": str(fam or ""),
                "base": float(base),
                "w_det": float(det_mult),
                "w_fam": float(fam_mult),
                "weighted": float(contrib),
                "reasons": reasons_short,
            }
        )

    # Confluence bonus v1: +confluence_weight*(unique_families-1)
    # Example: 2 families => +0.25, 3 families => +0.50
    for ddir in ("BUY", "SELL"):
        fam_n = len(by_dir[ddir]["families"])
        bonus = float(fam_bonus) * max(0, fam_n - 1)
        by_dir[ddir]["bonus"] = bonus
        
        # Correlation discount v1: reduce score for correlated detector pairs
        det_list = [str(h.detector) for h in by_dir[ddir]["hits"]]
        corr_discount, corr_pairs = _compute_correlation_discount(det_list)
        by_dir[ddir]["correlation_discount"] = corr_discount
        by_dir[ddir]["correlation_pairs"] = corr_pairs
        
        # Final score = raw + bonus - discount
        by_dir[ddir]["score_total"] = float(by_dir[ddir]["score"] + bonus - corr_discount)

    buy_score = float(by_dir["BUY"].get("score_total", 0.0))
    sell_score = float(by_dir["SELL"].get("score_total", 0.0))

    # Prepare breakdown (single-source; based on the same values used above)
    buy_contribs_sorted = sorted(
        list(by_dir["BUY"].get("contribs") or []),
        key=lambda d: float(d.get("weighted") or 0.0),
        reverse=True,
    )
    sell_contribs_sorted = sorted(
        list(by_dir["SELL"].get("contribs") or []),
        key=lambda d: float(d.get("weighted") or 0.0),
        reverse=True,
    )

    evidence: Dict[str, Any] = {
        "regime": regime_s,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "min_score": float(spec_obj.min_score),
        "epsilon": float(eps),
        "family_bonus": float(fam_bonus),
        # Back-compat keys for existing logs/tests
        "conflict_epsilon": float(eps),
        "confluence_weight": float(fam_bonus),
        "detectors_hit_buy": [h.detector for h in by_dir["BUY"]["hits"]],
        "detectors_hit_sell": [h.detector for h in by_dir["SELL"]["hits"]],
        "families_buy": sorted(by_dir["BUY"]["families"]),
        "families_sell": sorted(by_dir["SELL"]["families"]),

        # Breakdown fields (v2)
        "buy_score_raw": float(by_dir["BUY"].get("score_raw", 0.0) or 0.0),
        "sell_score_raw": float(by_dir["SELL"].get("score_raw", 0.0) or 0.0),
        "buy_score_weighted": float(by_dir["BUY"].get("score", 0.0) or 0.0),
        "sell_score_weighted": float(by_dir["SELL"].get("score", 0.0) or 0.0),
        "confluence_bonus_buy": float(by_dir["BUY"].get("bonus", 0.0) or 0.0),
        "confluence_bonus_sell": float(by_dir["SELL"].get("bonus", 0.0) or 0.0),
        
        # Correlation discount fields (v2)
        "correlation_discount_buy": float(by_dir["BUY"].get("correlation_discount", 0.0) or 0.0),
        "correlation_discount_sell": float(by_dir["SELL"].get("correlation_discount", 0.0) or 0.0),
        "correlation_pairs_buy": dict(by_dir["BUY"].get("correlation_pairs", {}) or {}),
        "correlation_pairs_sell": dict(by_dir["SELL"].get("correlation_pairs", {}) or {}),
    }

    buy_ok = buy_score >= float(spec_obj.min_score)
    sell_ok = sell_score >= float(spec_obj.min_score)

    if buy_ok and sell_ok:
        delta = abs(buy_score - sell_score)
        evidence["conflict_delta"] = float(delta)
        # Inclusive boundary with small tolerance for float rounding.
        if float(delta) <= float(eps) + 1e-12:
            # Winner/"best" side context for debugging.
            best_side = "BUY" if buy_score >= sell_score else "SELL"
            top_hit_contribs = buy_contribs_sorted if best_side == "BUY" else sell_contribs_sorted
            evidence["score_breakdown"] = {
                "strategy_id": getattr(spec_obj, "strategy_id", None),
                "regime": regime_s,
                "buy_score_raw": evidence["buy_score_raw"],
                "sell_score_raw": evidence["sell_score_raw"],
                "buy_score_weighted": evidence["buy_score_weighted"],
                "sell_score_weighted": evidence["sell_score_weighted"],
                "confluence_bonus_buy": evidence["confluence_bonus_buy"],
                "confluence_bonus_sell": evidence["confluence_bonus_sell"],
                "final_direction": None,
                "final_score": float(max(buy_score, sell_score)),
                "best_side": best_side,
                "top_hit_contribs": list(top_hit_contribs)[: int(getattr(spec_obj, "max_top_hits", 3) or 3)],
            }
            return CombineResult(
                ok=False,
                direction=None,
                score=max(buy_score, sell_score),
                fail_reason="CONFLICT_SCORE",
                evidence=evidence,
            )

    if not buy_ok and not sell_ok:
        best_side = "BUY" if buy_score >= sell_score else "SELL"
        top_hit_contribs = buy_contribs_sorted if best_side == "BUY" else sell_contribs_sorted
        evidence["score_breakdown"] = {
            "strategy_id": getattr(spec_obj, "strategy_id", None),
            "regime": regime_s,
            "buy_score_raw": evidence["buy_score_raw"],
            "sell_score_raw": evidence["sell_score_raw"],
            "buy_score_weighted": evidence["buy_score_weighted"],
            "sell_score_weighted": evidence["sell_score_weighted"],
            "confluence_bonus_buy": evidence["confluence_bonus_buy"],
            "confluence_bonus_sell": evidence["confluence_bonus_sell"],
            "final_direction": None,
            "final_score": float(max(buy_score, sell_score)),
            "best_side": best_side,
            "top_hit_contribs": list(top_hit_contribs)[: int(getattr(spec_obj, "max_top_hits", 3) or 3)],
        }
        return CombineResult(
            ok=False,
            direction=None,
            score=max(buy_score, sell_score),
            fail_reason="SCORE_BELOW_MIN",
            evidence=evidence,
        )

    direction: Literal["BUY", "SELL"] = "BUY" if buy_score > sell_score else "SELL"
    score = buy_score if direction == "BUY" else sell_score

    evidence["direction"] = direction
    evidence["score"] = float(score)
    evidence["detectors_hit"] = (
        evidence["detectors_hit_buy"] if direction == "BUY" else evidence["detectors_hit_sell"]
    )

    # Winner-side breakdown
    top_hit_contribs = buy_contribs_sorted if direction == "BUY" else sell_contribs_sorted
    evidence["score_breakdown"] = {
        "strategy_id": getattr(spec_obj, "strategy_id", None),
        "regime": regime_s,
        "buy_score_raw": evidence["buy_score_raw"],
        "sell_score_raw": evidence["sell_score_raw"],
        "buy_score_weighted": evidence["buy_score_weighted"],
        "sell_score_weighted": evidence["sell_score_weighted"],
        "confluence_bonus_buy": evidence["confluence_bonus_buy"],
        "confluence_bonus_sell": evidence["confluence_bonus_sell"],
        "final_direction": direction,
        "final_score": float(score),
        "best_side": direction,
        "top_hit_contribs": list(top_hit_contribs)[: int(getattr(spec_obj, "max_top_hits", 3) or 3)],
    }

    return CombineResult(ok=True, direction=direction, score=float(score), evidence=evidence)
