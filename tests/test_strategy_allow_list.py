"""tests.test_strategy_allow_list

Step 6.3: ensure strategy detector allow-list is enforced.

We mock the plugin registry loader to capture which detector names the engine
attempts to instantiate for a given StrategySpec.

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


def test_allow_list_detectors_only(monkeypatch: pytest.MonkeyPatch):
    from core.primitives import StructureResult
    from core.types import Regime
    from core.user_core_engine import scan_pair_cached_indicator_free

    # Force a stable regime.
    def fake_analyze_structure(*args, **kwargs):
        return StructureResult(ok=True, regime=Regime.RANGE.value, evidence={"hh": 1, "hl": 1, "lh": 1, "ll": 1})

    def fake_compute_primitives(*args, **kwargs):
        return SimpleNamespace(structure_trend=None)

    import core.primitives as primitives_mod

    monkeypatch.setattr(primitives_mod, "analyze_structure", fake_analyze_structure)
    monkeypatch.setattr(primitives_mod, "compute_primitives", fake_compute_primitives)

    # Capture allow-list detector names passed into registry.
    captured = {"names": None}

    class FakeDetector:
        def __init__(self, name: str):
            self._name = name
            self.meta = SimpleNamespace(supported_regimes={Regime.RANGE.value})

        def is_enabled(self):
            return True

        def get_name(self):
            return self._name

        def get_family(self):
            return "range"

        def detect(self, candles, primitives, context):
            # Always no-match
            return SimpleNamespace(match=False)

    def fake_load_from_profile(p):
        det_cfg = (p or {}).get("detectors") or {}
        captured["names"] = sorted([str(k) for k in det_cfg.keys()])
        return [FakeDetector(name) for name in det_cfg.keys()]

    import engines.detectors as det_mod

    monkeypatch.setattr(det_mod.detector_registry, "load_from_profile", fake_load_from_profile)

    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "engine_version": "indicator_free_v1",
        "strategies": [
            {
                "strategy_id": "s1",
                "enabled": True,
                "min_score": 0.0,
                "min_rr": 0.0,
                "allowed_regimes": ["RANGE"],
                "detectors": ["range_box_edge"],
            }
        ],
    }

    res = scan_pair_cached_indicator_free("EURUSD", profile, _make_candles(60), _make_candles(30))

    # Engine should only attempt to load the allow-listed detector.
    assert captured["names"] == ["range_box_edge"]

    # No hits => no setup
    assert res.has_setup is False
