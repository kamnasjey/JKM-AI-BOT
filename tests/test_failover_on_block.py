from __future__ import annotations

import time

from core.engine_blocks import Setup
from core.user_core_engine import ScanResult
from scanner_service import ScannerService
from scanner_state import SignalStateStore


def _mk_result(*, pair: str, strategy_id: str, direction: str, score: float, rr: float) -> ScanResult:
    setup = Setup(pair=pair, direction=direction, entry=1.0, sl=0.9, tp=1.2, rr=rr, trend_info=None, fibo_info=None)
    debug = {"strategy_id": strategy_id, "score": float(score), "min_score": 0.0}
    reasons = [f"DETECTOR|x", f"SCORE|{score:.2f}", "MIN_SCORE|0.00", f"RR|{rr:.2f}"]
    return ScanResult(pair=pair, has_setup=True, setup=setup, reasons=reasons, debug=debug)


def test_failover_on_block_picks_next_candidate_when_enabled(tmp_path, monkeypatch):
    service = ScannerService()
    service._state_store = SignalStateStore(path=str(tmp_path / "signal_state.json"))
    service._state_loaded = True

    # Force failover enabled
    import config as _cfg

    monkeypatch.setattr(_cfg, "STRATEGY_FAILOVER_ON_BLOCK", True)

    symbol = "EURUSD"
    tf = "M15"
    now_ts = 1_700_000_000.0

    # Candidate A is best but blocked by cooldown
    a = _mk_result(pair=symbol, strategy_id="A", direction="BUY", score=1.10, rr=2.0)
    b = _mk_result(pair=symbol, strategy_id="B", direction="BUY", score=1.00, rr=2.0)

    key_a = service._make_persistent_signal_key(symbol=symbol, timeframe=tf, strategy_id="A", direction="BUY")
    service._state_store.record_sent(key_a, now_ts - 60, symbol, direction="BUY", timeframe=tf, strategy_id="A")

    strategies = [
        {"strategy_id": "A", "cooldown_minutes": 30, "daily_limit": 100},
        {"strategy_id": "B", "cooldown_minutes": 30, "daily_limit": 100},
    ]

    chosen, meta = service._select_candidate_after_governance(
        ranked_results=[a, b],
        symbol=symbol,
        entry_tf=tf,
        tz_offset_hours=0,
        strategies=strategies,
        active_strategy=strategies[0],
        profile={},
        now_ts=now_ts,
    )

    assert chosen is b
    assert meta.get("used_failover") is True
    assert meta.get("blocked_winner_strategy_id") == "A"
    assert meta.get("blocked_reason") == "COOLDOWN_ACTIVE"


def test_failover_disabled_returns_none_and_reports_blocked_winner(tmp_path, monkeypatch):
    service = ScannerService()
    service._state_store = SignalStateStore(path=str(tmp_path / "signal_state.json"))
    service._state_loaded = True

    import config as _cfg

    monkeypatch.setattr(_cfg, "STRATEGY_FAILOVER_ON_BLOCK", False)

    symbol = "EURUSD"
    tf = "M15"
    now_ts = 1_700_000_000.0

    a = _mk_result(pair=symbol, strategy_id="A", direction="BUY", score=1.10, rr=2.0)
    b = _mk_result(pair=symbol, strategy_id="B", direction="BUY", score=1.00, rr=2.0)

    key_a = service._make_persistent_signal_key(symbol=symbol, timeframe=tf, strategy_id="A", direction="BUY")
    service._state_store.record_sent(key_a, now_ts - 60, symbol, direction="BUY", timeframe=tf, strategy_id="A")

    strategies = [
        {"strategy_id": "A", "cooldown_minutes": 30, "daily_limit": 100},
        {"strategy_id": "B", "cooldown_minutes": 30, "daily_limit": 100},
    ]

    chosen, meta = service._select_candidate_after_governance(
        ranked_results=[a, b],
        symbol=symbol,
        entry_tf=tf,
        tz_offset_hours=0,
        strategies=strategies,
        active_strategy=strategies[0],
        profile={},
        now_ts=now_ts,
    )

    assert chosen is None
    assert meta.get("blocked_winner_strategy_id") == "A"
    assert meta.get("blocked_reason") == "COOLDOWN_ACTIVE"
