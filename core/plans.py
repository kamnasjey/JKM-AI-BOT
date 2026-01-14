from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional


PlanId = str


@dataclass(frozen=True)
class PlanSpec:
    plan_id: PlanId
    label: str
    max_pairs: int


PLANS: dict[PlanId, PlanSpec] = {
    "free": PlanSpec(plan_id="free", label="Free", max_pairs=2),
    "pro": PlanSpec(plan_id="pro", label="Pro", max_pairs=5),
    "pro_plus": PlanSpec(plan_id="pro_plus", label="Pro+", max_pairs=15),
}


def normalize_plan_id(raw: Any) -> PlanId:
    s = str(raw or "").strip().lower()
    if s in {"", "free"}:
        return "free"
    if s in {"pro", "paid"}:
        return "pro"
    if s in {"pro+", "pro_plus", "proplus", "plus"}:
        return "pro_plus"
    return "free"


def plan_max_pairs(plan_id: Any) -> int:
    pid = normalize_plan_id(plan_id)
    return int(PLANS[pid].max_pairs)


def effective_plan_id(profile: Optional[dict[str, Any]]) -> PlanId:
    if not isinstance(profile, dict):
        return "free"
    pid = normalize_plan_id(profile.get("plan"))
    status = str(profile.get("plan_status") or "active").strip().lower()
    # Treat anything not active as free for enforcement.
    if status != "active":
        return "free"
    return pid


def effective_max_pairs(profile: Optional[dict[str, Any]]) -> int:
    return plan_max_pairs(effective_plan_id(profile))


def canon_symbol(sym: Any) -> str:
    return str(sym or "").upper().strip().replace("/", "").replace(" ", "")


def normalize_pairs(pairs: Any) -> list[str]:
    if not isinstance(pairs, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in pairs:
        s = canon_symbol(raw)
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def clamp_pairs(pairs: Any, max_pairs: int) -> list[str]:
    cleaned = normalize_pairs(pairs)
    if max_pairs <= 0:
        return []
    return cleaned[: int(max_pairs)]


def validate_pairs(pairs: Any, max_pairs: int) -> tuple[bool, str]:
    cleaned = normalize_pairs(pairs)
    if max_pairs < 0:
        max_pairs = 0
    if len(cleaned) > int(max_pairs):
        return False, f"Too many pairs (max {int(max_pairs)})."
    return True, ""
