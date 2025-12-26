from __future__ import annotations

from core.engine_blocks import Setup
from core.user_core_engine import ScanResult
from scanner_service import ScannerService
from scanner_state import SignalStateStore


def _mk_result(*, pair: str, strategy_id: str, direction: str, score: float, rr: float) -> ScanResult:
    setup = Setup(pair=pair, direction=direction, entry=1.0, sl=0.9, tp=1.2, rr=rr, trend_info=None, fibo_info=None)
    debug = {"strategy_id": strategy_id, "score": float(score), "min_score": 0.0, "detectors_hit": ["d1", "d2"]}
    reasons = [f"SCORE|{score:.2f}", "MIN_SCORE|0.00", f"RR|{rr:.2f}"]
    return ScanResult(pair=pair, has_setup=True, setup=setup, reasons=reasons, debug=debug)


def test_log_contract_failover_pair_ok_fields(tmp_path, monkeypatch):
    service = ScannerService()
    service._state_store = SignalStateStore(path=str(tmp_path / "signal_state.json"))
    service._state_loaded = True

    import config as _cfg

    monkeypatch.setattr(_cfg, "STRATEGY_FAILOVER_ON_BLOCK", True)

    symbol = "EURUSD"
    tf = "M15"
    now_ts = 1_700_000_000.0

    a = _mk_result(pair=symbol, strategy_id="A", direction="BUY", score=1.10, rr=2.0)
    b = _mk_result(pair=symbol, strategy_id="B", direction="BUY", score=1.00, rr=2.0)

    # Block A by recording a recent send under the hashed key.
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
    assert meta["used_failover"] is True
    assert meta["blocked_winner_strategy_id"] == "A"
    assert meta["blocked_reason"] == "COOLDOWN_ACTIVE"

    # Contract: final winner fields are from chosen (B)
    assert chosen.debug["strategy_id"] == "B"
    assert float(chosen.debug["score"]) == 1.00
