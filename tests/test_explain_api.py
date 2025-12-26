from __future__ import annotations

from typing import Any, Dict

from core.explain import build_pair_none_explain, build_pair_ok_explain


def _assert_required(payload: Dict[str, Any]) -> None:
    assert isinstance(payload, dict)
    assert payload.get("schema_version") == 1
    for k in ("symbol", "tf", "scan_id", "strategy_id", "status", "reason", "summary", "details", "evidence"):
        assert k in payload
    assert isinstance(payload["details"], dict)
    assert isinstance(payload["evidence"], dict)
    assert isinstance(payload["summary"], str)
    assert payload["summary"].strip() != ""


def test_explain_none_minimal_na_safe() -> None:
    payload = build_pair_none_explain(
        symbol="EURUSD",
        tf="M15",
        scan_id="scan_1",
        strategy_id="s1",
        reason="NO_HITS",
        debug=None,
        governance=None,
    )
    _assert_required(payload)
    assert payload["status"] == "NONE"
    assert payload["reason"] == "NO_HITS"
    # NA-safe keys always present
    assert "regime" in payload["details"]
    assert "score_breakdown" in payload["evidence"]


def test_explain_none_reason_stable_prefixes() -> None:
    payload = build_pair_none_explain(
        symbol="XAUUSD",
        tf="M15",
        scan_id="scan_2",
        strategy_id="s2",
        reason="SCORE_BELOW_MIN|0.45<0.60",
        debug={"buy_score": 0.45, "sell_score": 0.12, "min_score": 0.60},
        governance=None,
    )
    _assert_required(payload)
    assert payload["reason"] == "SCORE_BELOW_MIN"
    assert "Оноо" in payload["summary"]


def test_explain_ok_prefers_breakdown_math() -> None:
    dbg = {
        "rr": 2.1,
        "regime": "RANGE",
        "score_breakdown": {
            "best_side": "BUY",
            "buy_score_weighted": 0.62,
            "confluence_bonus_buy": 0.12,
            "final_score": 0.74,
            "top_hit_contribs": [
                {"detector": "d1", "weighted": 0.30},
                {"detector": "d2", "weighted": 0.22},
            ],
        },
    }
    payload = build_pair_ok_explain(
        symbol="EURUSD",
        tf="M15",
        scan_id="scan_3",
        strategy_id="s3",
        debug=dbg,
        governance=None,
    )
    _assert_required(payload)
    assert payload["status"] == "OK"
    assert payload["reason"] == "OK"
    # Should reflect breakdown-derived values
    assert payload["details"]["direction"] in ("BUY", "SELL", "NA")
    assert payload["details"]["score"] != "NA"
    assert payload["details"]["score_raw"] != "NA"
    assert payload["details"]["bonus"] != "NA"


def test_regime_normalization_uppercase() -> None:
    payload = build_pair_ok_explain(
        symbol="EURUSD",
        tf="M15",
        scan_id="scan_regime",
        strategy_id="s1",
        debug={
            "regime": "range",
            "score_breakdown": {
                "best_side": "BUY",
                "buy_score_weighted": 0.40,
                "confluence_bonus_buy": 0.00,
                "final_score": 0.40,
                "top_hit_contribs": [
                    {"detector": "d1", "weighted": 0.40},
                ],
            },
        },
        governance=None,
    )
    _assert_required(payload)
    assert payload["details"]["regime"] == "RANGE"
    assert "regime=RANGE" in payload["summary"]


def test_top_contribs_sum_matches_raw_or_falls_back() -> None:
    # Case 1: consistent => numeric (d1(0.30), d2(0.10))
    payload_ok = build_pair_ok_explain(
        symbol="EURUSD",
        tf="M15",
        scan_id="scan_top_ok",
        strategy_id="s1",
        debug={
            "score_breakdown": {
                "best_side": "BUY",
                "buy_score_weighted": 0.40,
                "confluence_bonus_buy": 0.00,
                "final_score": 0.40,
                "top_hit_contribs": [
                    {"detector": "d1", "weighted": 0.30},
                    {"detector": "d2", "weighted": 0.10},
                ],
            },
        },
        governance=None,
    )
    assert payload_ok["details"].get("top_contribs_inconsistent") is False
    assert "(" in str(payload_ok["details"].get("top_contribs"))

    # Case 2: inconsistent => names-only
    payload_bad = build_pair_ok_explain(
        symbol="EURUSD",
        tf="M15",
        scan_id="scan_top_bad",
        strategy_id="s1",
        debug={
            "score_breakdown": {
                "best_side": "BUY",
                "buy_score_weighted": 0.50,
                "confluence_bonus_buy": 0.00,
                "final_score": 0.50,
                "top_hit_contribs": [
                    {"detector": "d1", "weighted": 0.30},
                    {"detector": "d2", "weighted": 0.10},
                ],
            },
        },
        governance=None,
    )
    assert payload_bad["details"].get("top_contribs_inconsistent") is True
    top_txt = str(payload_bad["details"].get("top_contribs"))
    assert "d1" in top_txt and "d2" in top_txt
    assert "(" not in top_txt


def test_rr_below_min_summary_includes_evidence_when_available() -> None:
    payload = build_pair_none_explain(
        symbol="XAUUSD",
        tf="M15",
        scan_id="scan_rr",
        strategy_id="s_rr",
        reason="RR_BELOW_MIN",
        debug={
            "setup_fail": {
                "rr": 1.20,
                "min_rr": 1.50,
                "entry_zone": "1.2340-1.2350",
                "entry_zone_width_pct": 0.20,
                "sl_dist": 0.010,
                "tp_dist": 0.015,
            }
        },
        governance=None,
    )
    assert payload["reason"] == "RR_BELOW_MIN"
    s = payload["summary"]
    assert "RR бага" in s
    assert "Entry=" in s
    assert "SL_dist=" in s
    assert "TP_dist=" in s


def test_rr_below_min_na_safe_when_missing() -> None:
    payload = build_pair_none_explain(
        symbol="XAUUSD",
        tf="M15",
        scan_id="scan_rr_na",
        strategy_id="s_rr",
        reason="RR_BELOW_MIN",
        debug={"rr": 1.20, "min_rr": 1.50},
        governance=None,
    )
    s = payload["summary"]
    assert "Entry=NA" in s
    assert "width=NA%" in s
    assert "SL_dist=NA" in s
    assert "TP_dist=NA" in s
