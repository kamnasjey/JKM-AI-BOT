from __future__ import annotations

from core.plans import (
    clamp_pairs,
    effective_max_pairs,
    effective_plan_id,
    normalize_plan_id,
    validate_pairs,
)


def test_normalize_plan_id() -> None:
    assert normalize_plan_id(None) == "free"
    assert normalize_plan_id("") == "free"
    assert normalize_plan_id("FREE") == "free"
    assert normalize_plan_id("pro") == "pro"
    assert normalize_plan_id("paid") == "pro"
    assert normalize_plan_id("pro+") == "pro_plus"
    assert normalize_plan_id("pro_plus") == "pro_plus"


def test_effective_plan_id_inactive() -> None:
    assert effective_plan_id({"plan": "pro", "plan_status": "canceled"}) == "free"
    assert effective_plan_id({"plan": "pro_plus", "plan_status": "inactive"}) == "free"


def test_effective_max_pairs_defaults() -> None:
    assert effective_max_pairs(None) == 3
    assert effective_max_pairs({}) == 3


def test_pairs_validation_and_clamp() -> None:
    ok, _ = validate_pairs(["EURUSD", "XAUUSD"], 3)
    assert ok

    ok, msg = validate_pairs(["EURUSD", "XAUUSD", "BTCUSD", "USDJPY"], 3)
    assert not ok
    assert "max 3" in msg

    assert clamp_pairs(["eurusd", "xauusd", "btcusd", "usdjpy"], 3) == [
        "EURUSD",
        "XAUUSD",
        "BTCUSD",
    ]
