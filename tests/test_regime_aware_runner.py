"""tests.test_regime_aware_runner

M2: Regime-aware runner filtering tests.

These tests validate:
- TREND-only detectors are not eligible in RANGE regime.
- When no eligible detectors remain, engine returns NO_DETECTORS_FOR_REGIME.

Run:
    pytest -q
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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


def test_range_regime_excludes_trend_only_detectors():
    from core.types import Regime
    from engines.detectors.price_action import StructureTrendDetector
    from engines.detectors.range import RangeBoxEdgeDetector

    detectors = [StructureTrendDetector({"enabled": True}), RangeBoxEdgeDetector({"enabled": True})]
    regime = Regime.RANGE.value

    eligible = [d for d in detectors if regime in d.meta.supported_regimes]

    names = {d.get_name() for d in eligible}
    assert "structure_trend" not in names
    assert "range_box_edge" in names


def test_no_eligible_detectors_returns_no_detectors_for_regime(monkeypatch: pytest.MonkeyPatch):
    from core.user_core_engine import scan_pair_cached_indicator_free
    from core.primitives import StructureResult
    from core.types import Regime

    # Force regime=RANGE regardless of candle/structure details.
    def fake_analyze_structure(*args, **kwargs):
        return StructureResult(ok=True, regime=Regime.RANGE.value, evidence={"hh": 2, "hl": 1, "lh": 2, "ll": 1})

    # Minimal primitives object; runner will exit before any detector runs.
    def fake_compute_primitives(*args, **kwargs):
        return SimpleNamespace(structure_trend=None)

    import core.primitives as primitives_mod

    monkeypatch.setattr(primitives_mod, "analyze_structure", fake_analyze_structure)
    monkeypatch.setattr(primitives_mod, "compute_primitives", fake_compute_primitives)

    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "detectors": {
            # TREND-only detector
            "structure_trend": {"enabled": True},
        },
    }

    trend_candles = _make_candles(60)
    entry_candles = _make_candles(30)

    res = scan_pair_cached_indicator_free("EURUSD", profile, trend_candles, entry_candles)

    assert res.has_setup is False
    assert any(r == "NO_DETECTORS_FOR_REGIME" for r in (res.reasons or []))

    dbg = res.debug or {}
    assert dbg.get("regime") == Regime.RANGE.value
    # detectors_total reflects eligible detectors after regime filtering.
    assert dbg.get("detectors_total") == 0
