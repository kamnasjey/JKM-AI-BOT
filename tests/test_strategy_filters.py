"""tests.test_strategy_filters

Step 6: StrategySpec filters in indicator-free engine.

Validates:
- allowed_regimes blocks scan when current regime not allowed
- detectors allow-list controls debug.detectors_total

Run:
    pytest -q
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _make_candles(n: int, *, start_price: float = 1.0, step: float = 0.0001):
    from engine_blocks import Candle

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out = []
    price = float(start_price)
    for i in range(n):
        t = start + timedelta(minutes=5 * i)
        o = price
        c = price + step
        h = max(o, c) + abs(step) * 0.5
        l = min(o, c) - abs(step) * 0.5
        out.append(Candle(time=t, open=o, high=h, low=l, close=c))
        price = c
    return out


def test_allowed_regimes_blocks(monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from core.primitives import StructureResult
    from core.types import Regime
    from core.user_core_engine import scan_pair_cached_indicator_free

    def fake_analyze_structure(*args, **kwargs):
        return StructureResult(ok=True, regime=Regime.TREND_BULL.value, evidence={"hh": 3, "hl": 2, "lh": 0, "ll": 0})

    def fake_compute_primitives(*args, **kwargs):
        return SimpleNamespace(structure_trend=None)

    import core.primitives as primitives_mod

    monkeypatch.setattr(primitives_mod, "analyze_structure", fake_analyze_structure)
    monkeypatch.setattr(primitives_mod, "compute_primitives", fake_compute_primitives)

    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "allowed_regimes": ["RANGE"],
        "detectors": ["range_box_edge"],
    }

    res = scan_pair_cached_indicator_free("EURUSD", profile, _make_candles(60), _make_candles(30))
    assert res.has_setup is False
    assert "REGIME_BLOCKED" in (res.reasons or [])
    assert (res.debug or {}).get("regime") == Regime.TREND_BULL.value


def test_detector_allowlist_sets_detectors_total(monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from core.primitives import StructureResult
    from core.types import Regime
    from core.user_core_engine import scan_pair_cached_indicator_free

    def fake_analyze_structure(*args, **kwargs):
        return StructureResult(ok=True, regime=Regime.RANGE.value, evidence={"hh": 1, "hl": 1, "lh": 1, "ll": 1})

    def fake_compute_primitives(*args, **kwargs):
        return SimpleNamespace(structure_trend=None)

    import core.primitives as primitives_mod

    monkeypatch.setattr(primitives_mod, "analyze_structure", fake_analyze_structure)
    monkeypatch.setattr(primitives_mod, "compute_primitives", fake_compute_primitives)

    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "detectors": ["range_box_edge"],
    }

    res = scan_pair_cached_indicator_free("EURUSD", profile, _make_candles(60), _make_candles(30))
    dbg = res.debug or {}
    assert dbg.get("detectors_total") == 1
