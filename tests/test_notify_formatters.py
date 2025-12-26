from __future__ import annotations

from notify.formatters import format_signal_message


def test_all_mode_short() -> None:
    explain = {
        "schema_version": 1,
        "symbol": "EURUSD",
        "tf": "M15",
        "scan_id": "scan_1",
        "strategy_id": "s1",
        "status": "OK",
        "reason": "OK",
        "summary": "BUY signal: score=0.50 (raw 0.50 + bonus 0.00), RR=2.00, regime=RANGE. Top: d1(0.50).",
        "details": {"direction": "BUY", "score": "0.50", "rr": "2.00", "regime": "RANGE"},
        "evidence": {},
    }
    msg = format_signal_message(explain, mode="all")
    assert "EURUSD" in msg
    assert "M15" in msg
    assert "strat=s1" in msg
    assert "\n" in msg  # 2 lines
    assert "BUY signal" in msg


def test_admin_mode_includes_breakdown() -> None:
    explain = {
        "schema_version": 1,
        "symbol": "EURUSD",
        "tf": "M15",
        "scan_id": "scan_2",
        "strategy_id": "s2",
        "status": "OK",
        "reason": "OK",
        "summary": "BUY signal...",
        "details": {
            "direction": "BUY",
            "score": "0.50",
            "rr": "2.00",
            "regime": "RANGE",
            "top_contribs": "d1(0.30), d2(0.20)",
            "params_digest": "abc123",
        },
        "evidence": {
            "setup_fail": {"rr": 1.2, "min_rr": 1.5},
            "governance": {"cooldown_remaining_s": 120},
        },
    }
    msg = format_signal_message(explain, mode="admin_only")
    assert "<b>Top:</b>" in msg
    assert "d1" in msg and "d2" in msg
    assert "<b>Params:</b>" in msg
    assert "digest=abc123" in msg
    # OK should never show failure diagnostics
    assert "<b>SetupFail:</b>" not in msg
    assert "<b>Governance:</b>" not in msg


def test_admin_ok_does_not_include_setupfail_or_governance() -> None:
    explain = {
        "schema_version": 1,
        "symbol": "EURUSD",
        "tf": "M15",
        "scan_id": "scan_ok",
        "strategy_id": "s_ok",
        "status": "OK",
        "reason": "OK",
        "summary": "BUY signal...",
        "details": {"direction": "BUY", "score": "0.50", "rr": "2.00", "regime": "RANGE"},
        "evidence": {"setup_fail": {"rr": 1.2}, "governance": {"cooldown_remaining_s": 120}},
    }
    msg = format_signal_message(explain, mode="admin_only")
    assert "<b>SetupFail:</b>" not in msg
    assert "<b>Governance:</b>" not in msg


def test_admin_none_rr_below_min_includes_setupfail() -> None:
    explain = {
        "schema_version": 1,
        "symbol": "EURUSD",
        "tf": "M15",
        "scan_id": "scan_none_rr",
        "strategy_id": "s_none",
        "status": "NONE",
        "reason": "RR_BELOW_MIN",
        "summary": "RR бага...",
        "details": {"regime": "RANGE"},
        "evidence": {"setup_fail": {"rr": 1.2, "min_rr": 1.5}, "governance": {"cooldown_remaining_s": 120}},
    }
    msg = format_signal_message(explain, mode="admin_only")
    assert "<b>SetupFail:</b>" in msg
    assert "rr=1.2" in msg or "rr=1.20" in msg
    assert "<b>Governance:</b>" not in msg


def test_admin_none_cooldown_includes_governance() -> None:
    explain = {
        "schema_version": 1,
        "symbol": "EURUSD",
        "tf": "M15",
        "scan_id": "scan_none_cd",
        "strategy_id": "s_none",
        "status": "NONE",
        "reason": "COOLDOWN_ACTIVE",
        "summary": "Cooldown...",
        "details": {"regime": "RANGE"},
        "evidence": {"setup_fail": {"rr": 1.2}, "governance": {"cooldown_remaining_s": 120}},
    }
    msg = format_signal_message(explain, mode="admin_only")
    assert "<b>Governance:</b>" in msg
    assert "cooldown_remaining_s=120" in msg
    assert "<b>SetupFail:</b>" not in msg


def test_admin_none_score_below_min_includes_top_contribs_if_present() -> None:
    explain = {
        "schema_version": 1,
        "symbol": "EURUSD",
        "tf": "M15",
        "scan_id": "scan_none_score",
        "strategy_id": "s_none",
        "status": "NONE",
        "reason": "SCORE_BELOW_MIN",
        "summary": "Оноо босгонд хүрсэнгүй...",
        "details": {"top_contribs": "d1(0.30), d2(0.10)", "regime": "RANGE"},
        "evidence": {},
    }
    msg = format_signal_message(explain, mode="admin_only")
    assert "<b>Top:</b>" in msg
    assert "d1" in msg


def test_na_safe_fields_dont_crash() -> None:
    explain = {
        "schema_version": 1,
        "symbol": None,
        "tf": "",
        "scan_id": "scan_3",
        "strategy_id": None,
        "status": "OK",
        "reason": "OK",
        "summary": "",
        "details": {},
        "evidence": {"setup_fail": "NA", "governance": None},
    }
    msg = format_signal_message(explain, mode="admin_only")
    assert isinstance(msg, str)
    assert "NA" in msg
