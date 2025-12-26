"""tests.test_multi_strategy_arbitration

Step 7: Multi-strategy arbitration (v1)

Winner selection:
    winner = max(candidates, key=lambda c: (c.score, -c.priority, c.rr or 0))

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


def _patch_regime_range(monkeypatch: pytest.MonkeyPatch):
    from core.primitives import StructureResult
    from core.types import Regime

    def fake_analyze_structure(*args, **kwargs):
        return StructureResult(ok=True, regime=Regime.RANGE.value, evidence={"hh": 1, "hl": 1, "lh": 1, "ll": 1})

    def fake_compute_primitives(*args, **kwargs):
        return SimpleNamespace(structure_trend=None)

    import core.primitives as primitives_mod

    monkeypatch.setattr(primitives_mod, "analyze_structure", fake_analyze_structure)
    monkeypatch.setattr(primitives_mod, "compute_primitives", fake_compute_primitives)


def _patch_registry(monkeypatch: pytest.MonkeyPatch, *, by_name: dict[str, dict]):
    """Patch detector_registry.load_from_profile to return fakes.

    by_name example:
        {
            "det_a": {"score": 1.10, "rr": 1.0},
            "det_b": {"score": 1.05, "rr": 2.0},
        }
    """

    from core.types import Regime

    class FakeDetector:
        def __init__(self, name: str, *, score: float, rr: float):
            self._name = name
            self._score = float(score)
            self._rr = float(rr)
            self.meta = SimpleNamespace(supported_regimes={Regime.RANGE.value, Regime.CHOP.value})

        def is_enabled(self):
            return True

        def get_name(self):
            return self._name

        def get_family(self):
            return "range"

        def detect(self, candles, primitives, context):
            last = candles[-1].close
            return SimpleNamespace(
                match=True,
                detector_name=self._name,
                direction="BUY",
                score_contrib=self._score,
                rr=self._rr,
                reasons=["hit"],
                evidence_dict={},
                entry=float(last),
                sl=float(last - 0.01),
                tp=float(last + 0.02),
            )

    def fake_load_from_profile(p):
        det_cfg = (p or {}).get("detectors") or {}
        names = [str(k) for k in det_cfg.keys()]
        out = []
        for name in names:
            spec = by_name.get(name)
            if not spec:
                continue
            out.append(FakeDetector(name, score=float(spec["score"]), rr=float(spec["rr"])))
        return out

    import engines.detectors as det_mod

    monkeypatch.setattr(det_mod.detector_registry, "load_from_profile", fake_load_from_profile)


@pytest.mark.parametrize(
    "case",
    [
        {
            "name": "score_wins",
            "a": {"score": 1.10, "priority": 100, "rr": 1.0},
            "b": {"score": 1.05, "priority": 1, "rr": 2.0},
            "winner": "A",
        },
        {
            "name": "priority_breaks_tie",
            "a": {"score": 1.00, "priority": 50, "rr": 1.0},
            "b": {"score": 1.00, "priority": 10, "rr": 1.0},
            "winner": "B",
        },
        {
            "name": "rr_breaks_tie",
            "a": {"score": 1.00, "priority": 50, "rr": 1.5},
            "b": {"score": 1.00, "priority": 50, "rr": 2.0},
            "winner": "B",
        },
    ],
    ids=lambda c: c["name"],
)
def test_multi_strategy_arbitration(monkeypatch: pytest.MonkeyPatch, case: dict):
    from core.user_core_engine import scan_pair_cached_indicator_free

    # Use detector names that exist in the real registry; loader drops unknown names.
    det_a = "range_box_edge"
    det_b = "sr_bounce"

    _patch_regime_range(monkeypatch)

    _patch_registry(
        monkeypatch,
        by_name={
            det_a: {"score": case["a"]["score"], "rr": case["a"]["rr"]},
            det_b: {"score": case["b"]["score"], "rr": case["b"]["rr"]},
        },
    )

    profile = {
        "engine_version": "indicator_free_v1",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "strategies": [
            {
                "strategy_id": "A",
                "enabled": True,
                "priority": int(case["a"]["priority"]),
                "min_score": 0.0,
                "min_rr": 0.0,
                "allowed_regimes": ["RANGE"],
                "detectors": [det_a],
            },
            {
                "strategy_id": "B",
                "enabled": True,
                "priority": int(case["b"]["priority"]),
                "min_score": 0.0,
                "min_rr": 0.0,
                "allowed_regimes": ["RANGE"],
                "detectors": [det_b],
            },
        ],
    }

    res = scan_pair_cached_indicator_free("EURUSD", profile, _make_candles(60), _make_candles(30))
    assert res.has_setup is True

    dbg = res.debug or {}
    assert dbg.get("candidates") == 2
    assert dbg.get("winner_strategy_id") == case["winner"]
    assert dbg.get("strategy_id") == case["winner"]

    candidates_top = str(dbg.get("candidates_top") or "")
    assert "A:" in candidates_top
    assert "B:" in candidates_top
