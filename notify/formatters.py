from __future__ import annotations

from typing import Any, Dict


def _na(v: Any) -> str:
    if v is None:
        return "NA"
    s = str(v).strip()
    return s if s else "NA"


def _is_na(v: Any) -> bool:
    return v is None or str(v).strip() in ("", "NA")


def _fmt_kv(label: str, v: Any) -> str:
    return f"{label}={_na(v)}"


def _format_dict_block(title: str, obj: Any, *, max_items: int = 12) -> str:
    if not isinstance(obj, dict) or not obj:
        return ""

    items = []
    for k in sorted(obj.keys()):
        if len(items) >= int(max_items):
            break
        val = obj.get(k)
        items.append(_fmt_kv(str(k), val))

    if not items:
        return ""

    body = ", ".join(items)
    return f"<b>{title}:</b> {body}"


def format_signal_message(explain: Dict[str, Any], mode: str) -> str:
    """Format Telegram message body from ExplainPayload.

    mode:
      - all: short (1–2 lines)
      - admin_only: includes diagnostics blocks
    """
    ex = explain if isinstance(explain, dict) else {}
    details = ex.get("details") if isinstance(ex.get("details"), dict) else {}
    evidence = ex.get("evidence") if isinstance(ex.get("evidence"), dict) else {}

    symbol = _na(ex.get("symbol"))
    tf = _na(ex.get("tf"))
    strategy_id = _na(ex.get("strategy_id"))
    status = _na(ex.get("status")).upper()
    reason = _na(ex.get("reason")).upper()
    summary = _na(ex.get("summary"))

    direction = _na(details.get("direction"))
    score = _na(details.get("score"))
    rr = _na(details.get("rr"))
    regime = _na(details.get("regime"))

    header = (
        f"⚡ <b>{symbol}</b> {tf} | strat={strategy_id} | {direction} "
        f"score={score} RR={rr} regime={regime} | {status}"
    )

    mode_s = str(mode or "all").strip().lower()
    if mode_s != "admin_only":
        # Keep compact: 1-2 lines
        return f"{header}\n{summary}"

    # admin_only: conditional diagnostics
    top_contribs = details.get("top_contribs")
    params_digest = details.get("params_digest")

    lines = [header, summary]

    if status == "OK":
        if not _is_na(top_contribs):
            lines.append(f"<b>Top:</b> {_na(top_contribs)}")
        if not _is_na(params_digest):
            lines.append(f"<b>Params:</b> digest={_na(params_digest)}")
        return "\n".join([ln for ln in lines if str(ln).strip()])

    # status == NONE: show only relevant failure diagnostics
    setupfail_reasons = {
        "RR_BELOW_MIN",
        "NO_ENTRY_TRIGGER",
        "NO_INVALIDATION_LEVEL",
        "NO_TARGETS_FOUND",
        "ENTRY_TOO_FAR",
        "ZONE_TOO_WIDE",
    }
    gov_reasons = {"COOLDOWN_ACTIVE", "DAILY_LIMIT_REACHED"}
    score_reasons = {"SCORE_BELOW_MIN", "CONFLICT_SCORE", "NO_HITS", "NO_DETECTORS_FOR_REGIME"}

    if reason in score_reasons and not _is_na(top_contribs):
        lines.append(f"<b>Top:</b> {_na(top_contribs)}")

    if not _is_na(params_digest):
        lines.append(f"<b>Params:</b> digest={_na(params_digest)}")

    if reason in setupfail_reasons:
        block = _format_dict_block("SetupFail", evidence.get("setup_fail"))
        if block:
            lines.append(block)

    if reason in gov_reasons:
        block = _format_dict_block("Governance", evidence.get("governance"))
        if block:
            lines.append(block)

    return "\n".join([ln for ln in lines if str(ln).strip()])
