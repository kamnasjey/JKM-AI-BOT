from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


Status = Literal["OK", "NONE"]


_REGIME_CANONICAL = {
    "RANGE": "RANGE",
    "CHOP": "CHOP",
    "TREND_BULL": "TREND_BULL",
    "TREND_BEAR": "TREND_BEAR",
}


def _normalize_regime(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return "NA"
    s_up = s.upper()

    # Common aliases
    if s_up in _REGIME_CANONICAL:
        return _REGIME_CANONICAL[s_up]
    if s_up in ("RNG", "RANGING", "SIDEWAYS"):
        return "RANGE"
    if s_up in ("CHOPPY", "NOISY"):
        return "CHOP"
    if s_up in ("BULL", "UP", "UPTREND", "TREND_UP"):
        return "TREND_BULL"
    if s_up in ("BEAR", "DOWN", "DOWNTREND", "TREND_DOWN"):
        return "TREND_BEAR"

    # Best-effort normalization for values like "trend_bull"
    s_up = s_up.replace("-", "_").replace(" ", "_")
    return _REGIME_CANONICAL.get(s_up, s_up)


def _na(v: Any) -> Any:
    return v if v is not None else "NA"


def _f2(v: Any) -> str:
    try:
        return f"{float(v):.2f}"
    except Exception:
        return "NA"


def _stable_reason(reason: Any) -> str:
    s = str(reason or "").strip()
    if not s:
        return "UNKNOWN"
    if s.startswith("SCORE_BELOW_MIN"):
        return "SCORE_BELOW_MIN"
    if s.startswith("CONFLICT_SCORE"):
        return "CONFLICT_SCORE"
    # Keep governance reason codes stable as-is
    for r in (
        "NO_HITS",
        "RR_BELOW_MIN",
        "COOLDOWN_ACTIVE",
        "DAILY_LIMIT_REACHED",
        "REGIME_BLOCKED",
        "NO_DETECTORS_FOR_REGIME",
        "SETUP_BUILD_FAILED",
        "PRIMITIVE_ERROR",
        "DATA_INSUFFICIENT",
    ):
        if s.startswith(r):
            return r
    # Otherwise treat token before '|' as stable code.
    return s.split("|")[0]


def _top_from_breakdown(bd: Any) -> str:
    if not isinstance(bd, dict):
        return "NA"
    items = bd.get("top_hit_contribs")
    if not isinstance(items, list) or not items:
        return "NA"
    parts = []
    for it in items[:3]:
        if not isinstance(it, dict):
            continue
        det = str(it.get("detector") or "").strip()
        if not det:
            continue
        try:
            w = float(it.get("weighted") or 0.0)
            parts.append(f"{det}({w:.2f})")
        except Exception:
            parts.append(det)
    return ", ".join(parts) if parts else "NA"


def _top_contribs_for_ok(
    bd: Any,
    *,
    score_raw: Optional[float],
    tolerance: float = 0.02,
) -> tuple[str, bool]:
    """Format top contribs safely.

    If numeric contribs (sum of shown weighted contribs) don't match score_raw
    within tolerance, fall back to names-only and mark as inconsistent.
    """
    if not isinstance(bd, dict):
        return ("NA", False)

    items = bd.get("top_hit_contribs")
    if not isinstance(items, list) or not items:
        return ("NA", False)

    contribs: list[tuple[str, Optional[float]]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        det = str(it.get("detector") or "").strip()
        if not det:
            continue
        w_val: Optional[float]
        try:
            w_val = float(it.get("weighted"))
        except Exception:
            w_val = None
        contribs.append((det, w_val))

    if not contribs:
        return ("NA", False)

    # If score_raw isn't available, show names only (deterministic, non-misleading)
    if score_raw is None:
        names = ", ".join([d for d, _ in contribs[:3]])
        return (names or "NA", False)

    sum_top = 0.0
    numeric_ok = True
    for _, w in contribs:
        if w is None:
            numeric_ok = False
            continue
        sum_top += float(w)

    if (not numeric_ok) or (abs(float(sum_top) - float(score_raw)) > float(tolerance)):
        names = ", ".join([d for d, _ in contribs[:3]])
        return (names or "NA", True)

    # Consistent => print numeric values
    shown = []
    for det, w in contribs[:3]:
        if w is None:
            shown.append(det)
        else:
            shown.append(f"{det}({w:.2f})")
    return (", ".join(shown) if shown else "NA", False)


def _summary_ok(details: Dict[str, Any]) -> str:
    direction = str(details.get("direction") or "NA")
    score = _f2(details.get("score"))
    score_raw = _f2(details.get("score_raw"))
    bonus = _f2(details.get("bonus"))
    rr = _f2(details.get("rr"))
    regime = str(details.get("regime") or "NA")
    top = str(details.get("top_contribs") or "NA")
    return (
        f"{direction} signal: score={score} (raw {score_raw} + bonus {bonus}), "
        f"RR={rr}, regime={regime}. Top: {top}."
    )


def _summary_none(reason: str, details: Dict[str, Any]) -> str:
    regime = str(details.get("regime") or "NA")

    if reason == "NO_HITS":
        return f"Энэ стратеги дээр тохирох detector hit олдсонгүй (regime={regime})."
    if reason == "SCORE_BELOW_MIN":
        buy = _f2(details.get("buy_score"))
        sell = _f2(details.get("sell_score"))
        ms = _f2(details.get("min_score"))
        return f"Оноо босгонд хүрсэнгүй: buy={buy}, sell={sell}, min={ms}."
    if reason == "RR_BELOW_MIN":
        rr = _f2(details.get("rr"))
        min_rr = _f2(details.get("min_rr"))

        entry_zone = str(details.get("entry_zone") or "NA")
        width_pct = details.get("entry_zone_width_pct")
        width_s = _f2(width_pct) if width_pct is not None else "NA"
        sl_dist = str(details.get("sl_dist") if details.get("sl_dist") is not None else "NA")
        tp_dist = str(details.get("tp_dist") if details.get("tp_dist") is not None else "NA")

        return (
            f"RR бага: rr={rr} < min_rr={min_rr}. "
            f"Entry={entry_zone} width={width_s}%, SL_dist={sl_dist}, TP_dist={tp_dist}."
        )
    if reason == "COOLDOWN_ACTIVE":
        remaining = _na(details.get("cooldown_remaining_s"))
        last_sent = _na(details.get("last_sent_ts"))
        return f"Cooldown идэвхтэй: үлдсэн={remaining}s (last_sent={last_sent})."
    if reason == "DAILY_LIMIT_REACHED":
        sent = _na(details.get("sent_today"))
        limit = _na(details.get("daily_limit"))
        return f"Өдрийн лимит хүрсэн: sent={sent}, limit={limit}."
    if reason == "CONFLICT_SCORE":
        return "BUY/SELL оноо зэрэгцсэн тул conflict."

    return f"Signal олдсонгүй: reason={reason} (regime={regime})."


@dataclass(frozen=True)
class ExplainPayload:
    schema_version: int
    symbol: str
    tf: str
    scan_id: str
    strategy_id: str
    status: Status
    reason: str
    summary: str
    details: Dict[str, Any]
    evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "symbol": str(self.symbol),
            "tf": str(self.tf),
            "scan_id": str(self.scan_id),
            "strategy_id": str(self.strategy_id),
            "status": self.status,
            "reason": str(self.reason),
            "summary": str(self.summary),
            "details": dict(self.details),
            "evidence": dict(self.evidence),
        }


def build_pair_ok_explain(
    *,
    symbol: str,
    tf: str,
    scan_id: str,
    strategy_id: str,
    debug: Optional[Dict[str, Any]] = None,
    governance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dbg = dict(debug or {})
    bd = dbg.get("score_breakdown") if isinstance(dbg.get("score_breakdown"), dict) else {}

    # Prefer breakdown as single source of truth.
    side = ""
    try:
        side = str(bd.get("best_side") or bd.get("final_direction") or "").upper()
    except Exception:
        side = ""
    if side not in ("BUY", "SELL"):
        side = ""

    score_raw = None
    bonus = None
    try:
        if side == "BUY":
            score_raw = float(bd.get("buy_score_weighted") or 0.0)
            bonus = float(bd.get("confluence_bonus_buy") or 0.0)
        elif side == "SELL":
            score_raw = float(bd.get("sell_score_weighted") or 0.0)
            bonus = float(bd.get("confluence_bonus_sell") or 0.0)
    except Exception:
        score_raw = None
        bonus = None

    # Canonical regime
    regime = _normalize_regime(dbg.get("regime") or bd.get("regime"))

    # Top contribs formatting (guard against stale/mismatched scales)
    top_text, inconsistent = _top_contribs_for_ok(bd, score_raw=score_raw)

    details: Dict[str, Any] = {
        "direction": _na(dbg.get("direction") or bd.get("final_direction") or side),
        "score": _na(dbg.get("score") or bd.get("final_score")),
        "score_raw": _na(score_raw if score_raw is not None else dbg.get("score_raw")),
        "bonus": _na(bonus if bonus is not None else dbg.get("bonus")),
        "rr": _na(dbg.get("rr")),
        "regime": _na(regime),
        "top_hits": _na(dbg.get("detectors_hit")),
        "top_contribs": _na(top_text),
        "top_contribs_inconsistent": bool(inconsistent),
        "params_digest": _na(dbg.get("params_digest")),
        "candidates_top": _na(dbg.get("candidates_top")),
        # Optional shadow coverage (when SHADOW_ALL_DETECTORS=1)
        "shadow_hits": _na(dbg.get("shadow_hits")),
        "shadow_hit_count": _na(dbg.get("shadow_hit_count")),
        "shadow_detectors_total": _na(dbg.get("shadow_detectors_total")),
    }

    evidence: Dict[str, Any] = {
        "setup_fail": _na(dbg.get("setup_fail")),
        "governance": _na(governance or dbg.get("governance")),
        "score_breakdown": _na(dbg.get("score_breakdown")),
        "regime_evidence": _na(dbg.get("regime_evidence")),
    }

    summary = _summary_ok(details)
    payload = ExplainPayload(
        schema_version=1,
        symbol=str(symbol),
        tf=str(tf),
        scan_id=str(scan_id),
        strategy_id=str(strategy_id),
        status="OK",
        reason="OK",
        summary=summary,
        details=details,
        evidence=evidence,
    )
    return payload.to_dict()


def build_pair_none_explain(
    *,
    symbol: str,
    tf: str,
    scan_id: str,
    strategy_id: str,
    reason: str,
    debug: Optional[Dict[str, Any]] = None,
    governance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dbg = dict(debug or {})
    stable = _stable_reason(reason)
    bd = dbg.get("score_breakdown") if isinstance(dbg.get("score_breakdown"), dict) else {}

    regime = _normalize_regime(dbg.get("regime") or bd.get("regime"))

    # Prefer setup_fail evidence for RR-related fields when available.
    sf = dbg.get("setup_fail") if isinstance(dbg.get("setup_fail"), dict) else {}

    rr_val = dbg.get("rr")
    min_rr_val = dbg.get("min_rr")
    try:
        if rr_val is None and isinstance(sf, dict):
            rr_val = sf.get("rr")
        if min_rr_val is None and isinstance(sf, dict):
            min_rr_val = sf.get("min_rr")
    except Exception:
        pass

    details: Dict[str, Any] = {
        "reason": stable,
        "regime": _na(regime),
        "buy_score": _na(dbg.get("buy_score")),
        "sell_score": _na(dbg.get("sell_score")),
        "min_score": _na(dbg.get("min_score")),
        "top_contribs": _na(dbg.get("top_contribs") or _top_from_breakdown(bd)),
        # RR-related (when available)
        "rr": _na(rr_val),
        "min_rr": _na(min_rr_val),
        # Governance fields (when available)
        "cooldown_remaining_s": _na(dbg.get("cooldown_remaining_s")),
        "last_sent_ts": _na(dbg.get("last_sent_ts")),
        "sent_today": _na(dbg.get("sent_today")),
        "daily_limit": _na(dbg.get("daily_limit")),
        # Optional shadow coverage (when SHADOW_ALL_DETECTORS=1)
        "shadow_hits": _na(dbg.get("shadow_hits")),
        "shadow_hit_count": _na(dbg.get("shadow_hit_count")),
        "shadow_detectors_total": _na(dbg.get("shadow_detectors_total")),
    }

    if stable == "RR_BELOW_MIN" and isinstance(sf, dict):
        for k in ("entry_zone", "entry_zone_width_pct", "sl_dist", "tp_dist"):
            if k in sf:
                details[k] = sf.get(k) if sf.get(k) is not None else "NA"

    evidence: Dict[str, Any] = {
        "setup_fail": _na(dbg.get("setup_fail")),
        "governance": _na(governance or dbg.get("governance")),
        "score_breakdown": _na(dbg.get("score_breakdown")),
        "regime_evidence": _na(dbg.get("regime_evidence")),
    }

    summary = _summary_none(stable, details)
    payload = ExplainPayload(
        schema_version=1,
        symbol=str(symbol),
        tf=str(tf),
        scan_id=str(scan_id),
        strategy_id=str(strategy_id),
        status="NONE",
        reason=str(stable),
        summary=summary,
        details=details,
        evidence=evidence,
    )
    return payload.to_dict()
