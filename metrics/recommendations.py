from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from metrics.alert_codes import (
    AVG_RR_LOW,
    COOLDOWN_BLOCKS_HIGH,
    OK_RATE_LOW,
    TOP_REASON_DOMINANCE,
    canonicalize_alert_code,
)


@dataclass(frozen=True)
class Action:
    type: str  # "edit_strategy"
    strategy_id: str
    changes: Dict[str, Dict[str, Any]]
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": str(self.type),
            "strategy_id": str(self.strategy_id),
            "changes": dict(self.changes),
            "rationale": str(self.rationale),
        }


@dataclass(frozen=True)
class Recommendation:
    code: str
    priority: int  # 1 = highest
    message: str
    actions: List[Action]
    patch_preview: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": str(self.code),
            "priority": int(self.priority),
            "message": str(self.message),
            "actions": [a.to_dict() for a in (self.actions or [])],
            "patch_preview": self.patch_preview,
        }


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _top_reason(summary: Dict[str, Any]) -> str:
    trs = summary.get("top_reasons")
    if not isinstance(trs, list) or not trs:
        return "NA"
    tr0 = trs[0] if isinstance(trs[0], dict) else {}
    return str(tr0.get("reason") or "NA").strip().upper() or "NA"


def _none_total(summary: Dict[str, Any]) -> int:
    total = _safe_int(summary.get("total_pairs"))
    ok = _safe_int(summary.get("ok_count"))
    return max(int(total) - int(ok), 0)


def _reason_pct(summary: Dict[str, Any], reason: str) -> Optional[float]:
    reason_u = str(reason or "").strip().upper()
    if not reason_u:
        return None

    none_total = _none_total(summary)
    if none_total <= 0:
        return 0.0

    trs = summary.get("top_reasons")
    if not isinstance(trs, list):
        return None

    count = 0
    for item in trs:
        if not isinstance(item, dict):
            continue
        r = str(item.get("reason") or "").strip().upper()
        if r == reason_u:
            count = _safe_int(item.get("count"))
            break

    return float(count) / float(none_total) if none_total > 0 else 0.0


def _pick_target_strategy_id(summary: Dict[str, Any], strategies_json: Optional[Dict[str, Any]]) -> Optional[str]:
    ts = summary.get("top_strategies_by_ok")
    if isinstance(ts, list) and ts and isinstance(ts[0], dict):
        sid = str(ts[0].get("strategy_id") or "").strip()
        if sid:
            return sid

    if isinstance(strategies_json, dict):
        raw = strategies_json.get("strategies")
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            sid = str(raw[0].get("strategy_id") or "").strip()
            if sid:
                return sid

    return None


def _find_strategy_obj(strategies_json: Dict[str, Any], strategy_id: str) -> Optional[Dict[str, Any]]:
    raw = strategies_json.get("strategies")
    if not isinstance(raw, list):
        return None
    for s in raw:
        if not isinstance(s, dict):
            continue
        if str(s.get("strategy_id") or "").strip() == str(strategy_id):
            return s
    return None


def _infer_families_from_detectors(detectors: List[str]) -> Set[str]:
    fams: Set[str] = set()
    for d in detectors:
        name = str(d or "").strip().lower()
        if not name:
            continue
        if name.startswith("fibo_"):
            fams.add("fibo")
        elif name.startswith("sr_"):
            fams.add("sr")
        elif name.startswith("range_") or "fakeout" in name:
            fams.add("range")
        elif name.startswith("structure_") or name.startswith("swing_"):
            fams.add("structure")
        else:
            # unknown family; keep generic bucket
            fams.add("other")
    return fams


def _choose_complementary_detector(detectors: List[str]) -> Optional[Tuple[str, str]]:
    """Return (detector_name, family) for a safe complementary detector to add."""
    cur = set([str(x).strip() for x in (detectors or []) if str(x).strip()])
    fams = _infer_families_from_detectors(list(cur))

    # Only suggest detectors that are actually registered.
    try:
        from engines.detectors import detector_registry

        known = set(detector_registry.list_detectors() or [])
    except Exception:
        known = set()

    # Prefer adding a known, registered detector name.
    candidates: List[Tuple[str, str]] = []
    if "fibo" not in fams:
        candidates.append(("fibo_retrace", "fibo"))
    if "structure" not in fams:
        candidates.append(("structure_trend", "structure"))
    if "sr" not in fams:
        candidates.append(("sr_bounce", "sr"))

    for name, fam in candidates:
        if name not in cur:
            if known and name not in known:
                continue
            return (name, fam)
    return None


def _bounded_lower_min_score(cur: Optional[float]) -> Optional[float]:
    if cur is None:
        return None
    # Lower by 0.2 by default, bounded to >= 0.5
    return max(float(cur) - 0.2, 0.5)


def _bounded_raise_confluence_bonus(cur: Optional[float]) -> Optional[float]:
    if cur is None:
        return None
    # Raise slightly, bounded to <= 1.0
    return min(float(cur) + 0.05, 1.0)


def build_patch_preview(strategies_json: Dict[str, Any], actions: List[Action], *, max_blocks: int = 3) -> str:
    """Create compact before/after snippets for only changed keys (dry-run)."""
    if not isinstance(strategies_json, dict) or not actions:
        return ""

    blocks: List[str] = []
    used = 0

    for a in actions:
        if used >= int(max_blocks):
            break
        if not isinstance(a, Action):
            continue
        if str(a.type) != "edit_strategy":
            continue
        sid = str(a.strategy_id or "").strip()
        if not sid:
            continue
        s = _find_strategy_obj(strategies_json, sid)
        if not isinstance(s, dict):
            continue

        changed_keys = list((a.changes or {}).keys())
        before_obj: Dict[str, Any] = {}
        after_obj: Dict[str, Any] = {}
        for k in changed_keys:
            before_obj[k] = s.get(k)
            try:
                after_obj[k] = (a.changes.get(k) or {}).get("to")
            except Exception:
                after_obj[k] = s.get(k)

        before_s = json.dumps(before_obj, ensure_ascii=False, separators=(",", ":"))
        after_s = json.dumps(after_obj, ensure_ascii=False, separators=(",", ":"))
        blocks.append(f"strategy={sid}\nbefore: {before_s}\nafter:  {after_s}")
        used += 1

    return "\n\n".join(blocks)


def _stable_patch_id(*, date: str, strategy_id: str, changes: Dict[str, Dict[str, Any]]) -> str:
    payload = {
        "date": str(date),
        "strategy_id": str(strategy_id),
        "changes": changes,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def _apply_changes_snapshot(strategy_obj: Dict[str, Any], changes: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    before: Dict[str, Any] = {}
    after: Dict[str, Any] = {}
    for k, spec in (changes or {}).items():
        if not isinstance(spec, dict):
            continue
        before[k] = strategy_obj.get(k)
        after_val = spec.get("to")
        after[k] = after_val
    return before, after


def save_patch_suggestions(
    *,
    out_path: str,
    date: str,
    strategies_json: Dict[str, Any],
    recommendations: List[Recommendation],
) -> None:
    """Persist patch suggestions for CLI application.

    Non-fatal: all IO errors are swallowed.
    Writes schema 1:
      {"schema": 1, "items": [ {patch_id, date, strategy_id, changes, before_snapshot, after_snapshot}, ... ]}
    """
    try:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    except Exception:
        return

    # Build items
    items: List[Dict[str, Any]] = []
    try:
        raw_strategies = strategies_json.get("strategies")
        if not isinstance(raw_strategies, list):
            raw_strategies = []

        by_id: Dict[str, Dict[str, Any]] = {}
        for s in raw_strategies:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("strategy_id") or "").strip()
            if sid:
                by_id[sid] = s

        for r in recommendations or []:
            for a in (r.actions or []):
                if not isinstance(a, Action):
                    continue
                if str(a.type) != "edit_strategy":
                    continue
                sid = str(a.strategy_id or "").strip()
                if not sid:
                    continue
                changes = a.changes if isinstance(a.changes, dict) else {}
                if not changes:
                    continue
                strategy_obj = by_id.get(sid)
                if not isinstance(strategy_obj, dict):
                    continue
                before, after = _apply_changes_snapshot(strategy_obj, changes)
                patch_id = _stable_patch_id(date=str(date), strategy_id=sid, changes=changes)
                items.append(
                    {
                        "patch_id": patch_id,
                        "date": str(date),
                        "strategy_id": sid,
                        "changes": changes,
                        "before_snapshot": before,
                        "after_snapshot": after,
                    }
                )
    except Exception:
        return

    if not items:
        return

    # Merge with existing by patch_id
    try:
        existing: Dict[str, Any] = {}
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as f:
                existing = json.load(f) or {}
        if not isinstance(existing, dict):
            existing = {}
        existing_items = existing.get("items") if isinstance(existing.get("items"), list) else []

        merged: Dict[str, Dict[str, Any]] = {}
        for it in existing_items:
            if isinstance(it, dict) and str(it.get("patch_id") or ""):
                merged[str(it.get("patch_id"))] = it
        for it in items:
            merged[str(it.get("patch_id"))] = it

        payload = {"schema": 1, "items": list(merged.values())}
        tmp = f"{out_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, out_path)
    except Exception:
        return


def generate_recommendations(
    summary: Dict[str, Any],
    *,
    alert_codes: Sequence[str] | Set[str] | None = None,
    strategies_json: Optional[Dict[str, Any]] = None,
    per_strategy: Optional[Dict[str, Any]] = None,
) -> List[Recommendation]:
    """Deterministic strategy-tuning suggestions (no AI).

    Inputs:
      - summary: DailySummary dict (from DailySummary.to_dict())
      - alert_codes: active guardrail codes for the day (may include aliases)
      - per_strategy: optional strategy stats (unused in v1)
    """
    _ = per_strategy  # reserved for future versions

    codes: Set[str] = set()
    for c in (alert_codes or []):
        codes.add(canonicalize_alert_code(str(c)))

    top_reason = _top_reason(summary)
    target_strategy_id = _pick_target_strategy_id(summary, strategies_json)
    target_strategy: Optional[Dict[str, Any]] = None
    if isinstance(strategies_json, dict) and target_strategy_id:
        target_strategy = _find_strategy_obj(strategies_json, target_strategy_id)

    recos: List[Recommendation] = []

    # Rule 1: OK_RATE_LOW + NO_HITS
    if OK_RATE_LOW in codes and top_reason == "NO_HITS":
        actions: List[Action] = []

        if target_strategy_id and isinstance(target_strategy, dict):
            changes: Dict[str, Dict[str, Any]] = {}

            # allowed_regimes expansion if not user-restricted
            locked = bool(target_strategy.get("allowed_regimes_locked") or target_strategy.get("regime_lock"))
            ar = target_strategy.get("allowed_regimes")
            if not locked and isinstance(ar, list):
                ar_u = [str(x).strip().upper() for x in ar if str(x).strip()]
                if len(ar_u) < 4:
                    default_all = ["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"]
                    missing = [r for r in default_all if r not in ar_u]
                    if missing:
                        to_ar = list(ar_u) + missing[: (4 - len(ar_u))]
                        changes["allowed_regimes"] = {"from": list(ar), "to": to_ar}

            # add 1 complementary detector if possible
            dets = target_strategy.get("detectors")
            if isinstance(dets, list):
                pick = _choose_complementary_detector([str(x) for x in dets])
                if pick is not None:
                    det_name, _fam = pick
                    to_dets = [str(x) for x in dets if str(x).strip()]
                    if det_name not in to_dets:
                        to_dets.append(det_name)
                        changes["detectors"] = {"from": list(dets), "to": to_dets}

            # relax params slightly via family_params (range)
            fam_params = target_strategy.get("family_params")
            if fam_params is None:
                fam_params = {}
            if isinstance(fam_params, dict):
                before_fp = dict(fam_params)
                range_fp = dict(before_fp.get("range") or {})
                # Default detector config uses edge_tolerance_frac=0.0015; relax a bit
                cur_tol = _safe_float(range_fp.get("edge_tolerance_frac"))
                if cur_tol is None:
                    cur_tol = 0.0015
                new_tol = min(float(cur_tol) + 0.0003, 0.0030)
                range_fp["edge_tolerance_frac"] = float(new_tol)
                after_fp = dict(before_fp)
                after_fp["range"] = range_fp
                changes["family_params"] = {"from": before_fp, "to": after_fp}

            # lower min_score slightly (bounded)
            cur_ms = _safe_float(target_strategy.get("min_score"))
            to_ms = _bounded_lower_min_score(cur_ms)
            if cur_ms is not None and to_ms is not None and float(to_ms) != float(cur_ms):
                changes["min_score"] = {"from": float(cur_ms), "to": float(to_ms)}

            if changes:
                actions.append(
                    Action(
                        type="edit_strategy",
                        strategy_id=target_strategy_id,
                        changes=changes,
                        rationale="Increase hits by broadening regimes, adding complementary detector coverage, relaxing range tolerances, and slightly lowering min_score.",
                    )
                )

        recos.append(
            Recommendation(
                code="RECO_OK_RATE_LOW_NO_HITS",
                priority=1,
                message="OK rate is low and most NONE decisions are NO_HITS: broaden opportunity or improve hit coverage.",
                actions=actions,
            )
        )

    # Rule 2: OK_RATE_LOW + SCORE_BELOW_MIN
    if OK_RATE_LOW in codes and top_reason == "SCORE_BELOW_MIN":
        actions: List[Action] = []
        if target_strategy_id and isinstance(target_strategy, dict):
            changes: Dict[str, Dict[str, Any]] = {}
            cur_ms = _safe_float(target_strategy.get("min_score"))
            to_ms = _bounded_lower_min_score(cur_ms)
            if cur_ms is not None and to_ms is not None and float(to_ms) != float(cur_ms):
                changes["min_score"] = {"from": float(cur_ms), "to": float(to_ms)}

            cur_cb = _safe_float(target_strategy.get("confluence_bonus_per_family"))
            to_cb = _bounded_raise_confluence_bonus(cur_cb)
            if cur_cb is not None and to_cb is not None and float(to_cb) != float(cur_cb):
                changes["confluence_bonus_per_family"] = {"from": float(cur_cb), "to": float(to_cb)}

            if changes:
                actions.append(
                    Action(
                        type="edit_strategy",
                        strategy_id=target_strategy_id,
                        changes=changes,
                        rationale="SCORE_BELOW_MIN suggests scoring gate is too strict; lower min_score and/or slightly increase confluence bonus.",
                    )
                )

        recos.append(
            Recommendation(
                code="RECO_OK_RATE_LOW_SCORE_BELOW_MIN",
                priority=1,
                message="OK rate is low and most NONE decisions are SCORE_BELOW_MIN: scoring is filtering too aggressively.",
                actions=actions,
            )
        )

    # Rule 3: AVG_RR_LOW
    if AVG_RR_LOW in codes:
        recos.append(
            Recommendation(
                code="RECO_AVG_RR_LOW",
                priority=2,
                message="Average RR is low: improve trade geometry by enforcing better RR and target/stop selection.",
                actions=[],
            )
        )

    # Rule 4: COOLDOWN_BLOCKS_HIGH
    if COOLDOWN_BLOCKS_HIGH in codes:
        recos.append(
            Recommendation(
                code="RECO_COOLDOWN_BLOCKS_HIGH",
                priority=3,
                message="Many pairs are blocked by cooldown: reduce repeated signals or adjust cooldown settings.",
                actions=[],
            )
        )

    # Rule 5: NO_DETECTORS_FOR_REGIME frequent
    # Either the explicit top reason dominance guardrail, or the reason itself is frequent.
    nd_pct = _reason_pct(summary, "NO_DETECTORS_FOR_REGIME")
    if (nd_pct is not None and nd_pct >= 0.25) or (TOP_REASON_DOMINANCE in codes and top_reason == "NO_DETECTORS_FOR_REGIME"):
        actions: List[Action] = []
        if target_strategy_id and isinstance(target_strategy, dict):
            changes: Dict[str, Dict[str, Any]] = {}

            ar = target_strategy.get("allowed_regimes")
            if isinstance(ar, list) and isinstance(summary.get("regimes"), list):
                ar_u = [str(x).strip().upper() for x in ar if str(x).strip()]
                observed = [
                    str(x.get("regime") or "").strip().upper()
                    for x in (summary.get("regimes") or [])
                    if isinstance(x, dict)
                ]
                observed = [x for x in observed if x]
                missing = [r for r in observed if r not in ar_u]
                if missing:
                    to_ar = list(ar_u) + missing[:2]
                    changes["allowed_regimes"] = {"from": list(ar), "to": to_ar}

            dets = target_strategy.get("detectors")
            if isinstance(dets, list):
                pick = _choose_complementary_detector([str(x) for x in dets])
                if pick is not None:
                    det_name, _fam = pick
                    to_dets = [str(x) for x in dets if str(x).strip()]
                    if det_name not in to_dets:
                        to_dets.append(det_name)
                        changes["detectors"] = {"from": list(dets), "to": to_dets}

            if changes:
                actions.append(
                    Action(
                        type="edit_strategy",
                        strategy_id=target_strategy_id,
                        changes=changes,
                        rationale="Ensure detectors exist for observed regimes by aligning allowed_regimes and enabling at least one complementary detector.",
                    )
                )

        recos.append(
            Recommendation(
                code="RECO_NO_DETECTORS_FOR_REGIME",
                priority=1,
                message="NO_DETECTORS_FOR_REGIME is frequent: align supported_regimes and allowed_regimes, and ensure detectors are registered.",
                actions=actions,
            )
        )

    # Deterministic ordering
    # Attach patch previews deterministically.
    if isinstance(strategies_json, dict):
        for i, r in enumerate(recos):
            actions = list(r.actions or [])
            preview = build_patch_preview(strategies_json, actions, max_blocks=3)
            if preview:
                recos[i] = Recommendation(
                    code=r.code,
                    priority=r.priority,
                    message=r.message,
                    actions=r.actions,
                    patch_preview=preview,
                )

    recos.sort(key=lambda r: (int(r.priority), str(r.code)))
    return recos


def format_tuning_suggestions(
    *,
    date: str,
    recommendations: Iterable[Recommendation],
    max_items: int = 3,
) -> str:
    recos = list(recommendations)
    recos = sorted(recos, key=lambda r: (int(r.priority), str(r.code)))
    top = recos[: int(max_items)]

    if not top:
        return f"🛠 Tuning Suggestions ({date}): NA"

    parts = []
    for i, r in enumerate(top, start=1):
        parts.append(f"{i}) {r.message}")

    return f"🛠 Tuning Suggestions ({date}): " + " ".join(parts)
