from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from metrics.alert_codes import (
    AVG_RR_LOW,
    COOLDOWN_BLOCKS_HIGH,
    OK_RATE_LOW,
    TOP_REASON_DOMINANCE,
    canonicalize_alert_code,
)
from state.metrics_alert_state import load_alert_state, save_alert_state_atomic


@dataclass(frozen=True)
class Alert:
    code: str
    severity: str  # "warn" | "critical"
    message: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": str(self.code),
            "severity": str(self.severity),
            "message": str(self.message),
            "details": dict(self.details),
        }


def _env_float(name: str) -> Optional[float]:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _env_int(name: str) -> Optional[int]:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, str) and v.strip().upper() == "NA":
        return None
    try:
        return float(v)
    except Exception:
        return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, str) and v.strip().upper() == "NA":
        return None
    try:
        return int(v)
    except Exception:
        return None


def _get_thresholds(config_module: Any = None) -> Dict[str, Any]:
    # Defaults
    ok_rate_min = 0.20
    avg_rr_min = 1.50
    cooldown_blocks_max = 20
    top_reason_max_pct = 0.60

    # Config overrides
    try:
        if config_module is not None:
            ok_rate_min = float(getattr(config_module, "OK_RATE_MIN", ok_rate_min))
            avg_rr_min = float(getattr(config_module, "AVG_RR_MIN", avg_rr_min))
            cooldown_blocks_max = int(getattr(config_module, "COOLDOWN_BLOCKS_MAX", cooldown_blocks_max))
            top_reason_max_pct = float(getattr(config_module, "TOP_REASON_MAX_PCT", top_reason_max_pct))
    except Exception:
        pass

    # Env overrides
    ok_rate_min = _env_float("OK_RATE_MIN") if _env_float("OK_RATE_MIN") is not None else ok_rate_min
    avg_rr_min = _env_float("AVG_RR_MIN") if _env_float("AVG_RR_MIN") is not None else avg_rr_min
    cooldown_blocks_max = (
        _env_int("COOLDOWN_BLOCKS_MAX") if _env_int("COOLDOWN_BLOCKS_MAX") is not None else cooldown_blocks_max
    )
    top_reason_max_pct = (
        _env_float("TOP_REASON_MAX_PCT") if _env_float("TOP_REASON_MAX_PCT") is not None else top_reason_max_pct
    )

    return {
        "OK_RATE_MIN": float(ok_rate_min),
        "AVG_RR_MIN": float(avg_rr_min),
        "COOLDOWN_BLOCKS_MAX": int(cooldown_blocks_max),
        "TOP_REASON_MAX_PCT": float(top_reason_max_pct),
    }


def evaluate_guardrails(summary: Dict[str, Any], *, config_module: Any = None) -> List[Alert]:
    """Evaluate guardrails using a DailySummary dict.

    Returns list of alerts (empty if healthy).
    """
    thresholds = _get_thresholds(config_module=config_module)

    date = str(summary.get("date") or "NA")
    total = _safe_int(summary.get("total_pairs")) or 0
    ok = _safe_int(summary.get("ok_count")) or 0
    ok_rate = _safe_float(summary.get("ok_rate"))
    avg_rr = _safe_float(summary.get("avg_rr"))
    cooldown_blocks = _safe_int(summary.get("cooldown_blocks")) or 0

    none_total = max(int(total) - int(ok), 0)

    top_reasons = summary.get("top_reasons") if isinstance(summary.get("top_reasons"), list) else []
    top_reason = "NA"
    top_reason_count = 0
    try:
        if top_reasons:
            tr0 = top_reasons[0] if isinstance(top_reasons[0], dict) else {}
            top_reason = str(tr0.get("reason") or "NA").upper()
            top_reason_count = int(tr0.get("count") or 0)
    except Exception:
        top_reason = "NA"
        top_reason_count = 0

    alerts: List[Alert] = []

    # OK rate
    if ok_rate is not None and ok_rate < float(thresholds["OK_RATE_MIN"]):
        alerts.append(
            Alert(
                code=OK_RATE_LOW,
                severity="critical",
                message=f"OK rate {ok_rate:.3f} < {float(thresholds['OK_RATE_MIN']):.3f}",
                details={"date": date, "ok_rate": ok_rate, "ok": ok, "total": total},
            )
        )

    # Avg RR
    if avg_rr is not None and avg_rr < float(thresholds["AVG_RR_MIN"]):
        alerts.append(
            Alert(
                code=AVG_RR_LOW,
                severity="warn",
                message=f"Avg RR {avg_rr:.3f} < {float(thresholds['AVG_RR_MIN']):.3f}",
                details={"date": date, "avg_rr": avg_rr, "ok": ok, "total": total},
            )
        )

    # Cooldown blocks
    if cooldown_blocks > int(thresholds["COOLDOWN_BLOCKS_MAX"]):
        alerts.append(
            Alert(
                code=COOLDOWN_BLOCKS_HIGH,
                severity="warn",
                message=f"Cooldown blocks {cooldown_blocks} > {int(thresholds['COOLDOWN_BLOCKS_MAX'])}",
                details={"date": date, "cooldown_blocks": cooldown_blocks, "total": total},
            )
        )

    # Top-reason dominance (currently only checks NO_HITS)
    if none_total > 0 and top_reason == "NO_HITS":
        pct = float(top_reason_count) / float(none_total) if none_total > 0 else 0.0
        if pct > float(thresholds["TOP_REASON_MAX_PCT"]):
            alerts.append(
                Alert(
                    code=TOP_REASON_DOMINANCE,
                    severity="warn",
                    message=f"NO_HITS {pct:.0%} > {float(thresholds['TOP_REASON_MAX_PCT']):.0%}",
                    details={
                        "date": date,
                        "none_total": none_total,
                        "no_hits": int(top_reason_count),
                        "pct": pct,
                        "top_reason": top_reason,
                    },
                )
            )

    return alerts


def _value_threshold_for_alert(
    code: str,
    summary: Dict[str, Any],
    thresholds: Dict[str, Any],
) -> Tuple[Optional[float], Optional[float]]:
    code = canonicalize_alert_code(code)
    if code == OK_RATE_LOW:
        return (_safe_float(summary.get("ok_rate")), float(thresholds.get("OK_RATE_MIN")))
    if code == AVG_RR_LOW:
        return (_safe_float(summary.get("avg_rr")), float(thresholds.get("AVG_RR_MIN")))
    if code == COOLDOWN_BLOCKS_HIGH:
        v = _safe_int(summary.get("cooldown_blocks"))
        thr = thresholds.get("COOLDOWN_BLOCKS_MAX")
        try:
            return (float(v) if v is not None else None, float(thr))
        except Exception:
            return (None, None)
    if code == TOP_REASON_DOMINANCE:
        # pct among NONE events
        total = _safe_int(summary.get("total_pairs")) or 0
        ok = _safe_int(summary.get("ok_count")) or 0
        none_total = max(int(total) - int(ok), 0)
        top_reasons = summary.get("top_reasons") if isinstance(summary.get("top_reasons"), list) else []
        top_reason = "NA"
        top_reason_count = 0
        try:
            if top_reasons and isinstance(top_reasons[0], dict):
                top_reason = str(top_reasons[0].get("reason") or "NA").upper()
                top_reason_count = int(top_reasons[0].get("count") or 0)
        except Exception:
            top_reason = "NA"
            top_reason_count = 0
        if none_total > 0 and top_reason == "NO_HITS":
            pct = float(top_reason_count) / float(none_total)
            return (pct, float(thresholds.get("TOP_REASON_MAX_PCT")))
        return (None, float(thresholds.get("TOP_REASON_MAX_PCT")))
    return (None, None)


def format_recovery_message(*, date: str, code: str, value: Optional[float], threshold: Optional[float]) -> str:
    v = "NA" if value is None else f"{float(value):.3f}"
    t = "NA" if threshold is None else f"{float(threshold):.3f}"
    return f"✅ Metrics Recovered ({date}): {code} resolved ({v} >= {t})"


def process_guardrails_stateful(
    summary: Dict[str, Any],
    *,
    state_path: str = "state/metrics_alert_state.json",
    config_module: Any = None,
) -> Dict[str, Any]:
    """Evaluate guardrails with persisted dedupe + recovery.

    Returns dict with:
      - trigger: alerts to notify (first trigger)
      - repeat: alerts repeated (log only unless env override)
      - recover: recovery items (each has code/message)
      - state: updated state dict
    """
    date = str(summary.get("date") or "NA")
    thresholds = _get_thresholds(config_module=config_module)

    triggered_now_raw = evaluate_guardrails(summary, config_module=config_module)
    # Canonicalize in case any caller constructs Alerts manually.
    triggered_now = [
        Alert(
            code=canonicalize_alert_code(getattr(a, "code", "NA")),
            severity=str(getattr(a, "severity", "warn")),
            message=str(getattr(a, "message", "")),
            details=dict(getattr(a, "details", {}) or {}),
        )
        for a in triggered_now_raw
    ]
    triggered_codes = {canonicalize_alert_code(a.code) for a in triggered_now}

    st = load_alert_state(state_path)
    alerts_state = st.get("alerts") if isinstance(st.get("alerts"), dict) else {}

    out_trigger: List[Alert] = []
    out_repeat: List[Alert] = []
    out_recover: List[Dict[str, Any]] = []

    repeat_notify = str(os.getenv("METRICS_ALERT_REPEAT_NOTIFY", "0") or "0").strip() == "1"

    # 1) Handle triggers (dedupe)
    for a in triggered_now:
        code = canonicalize_alert_code(getattr(a, "code", "NA"))
        prev = alerts_state.get(code) if isinstance(alerts_state.get(code), dict) else {}
        prev_active = bool(prev.get("active"))
        prev_date = str(prev.get("last_triggered_date") or "")

        value, thr = _value_threshold_for_alert(code, summary, thresholds)
        updated = {
            "last_triggered_date": date,
            "active": True,
            "last_value": value,
            "threshold": thr,
            "severity": str(a.severity),
        }
        alerts_state[code] = updated

        if not prev_active:
            out_trigger.append(a)
        else:
            # Active already => repeat (same day or later)
            if prev_date != date:
                out_repeat.append(a)
            else:
                out_repeat.append(a)

            if repeat_notify:
                out_trigger.append(a)

    # 2) Handle recovery
    for code, prev in list(alerts_state.items()):
        if not isinstance(prev, dict):
            continue
        if not bool(prev.get("active")):
            continue
        if canonicalize_alert_code(str(code)) in triggered_codes:
            continue

        # Was active, not triggered today => recovered
        canon_code = canonicalize_alert_code(str(code))
        value, thr = _value_threshold_for_alert(canon_code, summary, thresholds)
        prev["active"] = False
        prev["last_recovered_date"] = date
        prev["last_value"] = value
        prev["threshold"] = thr
        # Ensure state key stays canonical.
        alerts_state.pop(str(code), None)
        alerts_state[str(canon_code)] = prev
        out_recover.append(
            {
                "code": str(canon_code),
                "message": format_recovery_message(date=date, code=str(canon_code), value=value, threshold=thr),
                "value": value,
                "threshold": thr,
            }
        )

    new_state = {"schema": 1, "alerts": alerts_state}
    save_alert_state_atomic(new_state, state_path)

    return {
        "trigger": out_trigger,
        "repeat": out_repeat,
        "recover": out_recover,
        "state": new_state,
    }


def format_alert_message(summary: Dict[str, Any], alerts: List[Alert]) -> str:
    date = str(summary.get("date") or "NA")
    ok_rate = summary.get("ok_rate")
    top_reason = "NA"
    try:
        trs = summary.get("top_reasons")
        if isinstance(trs, list) and trs and isinstance(trs[0], dict):
            top_reason = str(trs[0].get("reason") or "NA")
    except Exception:
        top_reason = "NA"

    top_strategy = "NA"
    try:
        ts = summary.get("top_strategies_by_ok")
        if isinstance(ts, list) and ts and isinstance(ts[0], dict):
            top_strategy = str(ts[0].get("strategy_id") or "NA")
    except Exception:
        top_strategy = "NA"

    parts = []
    for a in alerts:
        parts.append(a.message)

    ok_rate_s = "NA"
    try:
        ok_rate_s = f"{float(ok_rate):.3f}"
    except Exception:
        ok_rate_s = "NA"

    joined = "; ".join(parts) if parts else "NA"
    return (
        f"📉 Metrics Alert ({date}): {joined}. "
        f"Context: ok_rate={ok_rate_s}, top_reason={top_reason}, top_strategy={top_strategy}."
    )
