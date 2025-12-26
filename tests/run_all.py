"""tests.run_all

Minimal QA gate for the indicator-free engine.

Run:
    python -m tests.run_all

Exits non-zero on failure.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=False, detail=detail)


def _ok(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name=name, ok=True, detail=detail)


def _make_m5_candles(
    *,
    count: int,
    start: datetime,
    start_price: float,
    step: float,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    price = start_price
    for i in range(count):
        t = start + timedelta(minutes=5 * i)
        open_p = price
        close_p = price + step
        high_p = max(open_p, close_p) + abs(step) * 0.5
        low_p = min(open_p, close_p) - abs(step) * 0.5
        out.append(
            {
                "time": t,
                "open": float(open_p),
                "high": float(high_p),
                "low": float(low_p),
                "close": float(close_p),
            }
        )
        price = close_p
    return out


def _make_candle_objs(m5_dicts: List[Dict[str, Any]]):
    from engine_blocks import Candle

    return [
        Candle(
            time=d["time"],
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
        )
        for d in m5_dicts
    ]


def check_cache_memoization() -> CheckResult:
    name = "1) Cache memoization"
    try:
        import resample_5m
        from market_data_cache import MarketDataCache

        calls = {"n": 0}
        orig = resample_5m.resample

        def wrapped(m5_candles, timeframe):
            calls["n"] += 1
            return orig(m5_candles, timeframe)

        resample_5m.resample = wrapped
        try:
            cache = MarketDataCache(max_len=5000)
            sym = "EURUSD"
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            candles = _make_m5_candles(count=300, start=start, start_price=1.1, step=0.0001)
            cache.upsert_candles(sym, candles)

            _ = cache.get_resampled(sym, "H1")
            _ = cache.get_resampled(sym, "H1")
            if calls["n"] != 1:
                return _fail(name, f"Expected 1 resample call, got {calls['n']}")

            # Upsert a newer candle → should invalidate and recompute.
            newer = _make_m5_candles(
                count=1,
                start=start + timedelta(minutes=5 * 300),
                start_price=1.1 + 300 * 0.0001,
                step=0.0001,
            )
            cache.upsert_candles(sym, newer)
            _ = cache.get_resampled(sym, "H1")
            if calls["n"] != 2:
                return _fail(name, f"Expected 2 resample calls after new candle, got {calls['n']}")

            return _ok(name)
        finally:
            resample_5m.resample = orig
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def check_detector_contract() -> CheckResult:
    name = "2) Detector contract"
    required_fields = ["match", "direction", "confidence", "setup_name", "evidence"]
    try:
        from engines.detectors.registry import detector_registry
        from core.primitives import compute_primitives

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        # Create clear uptrend candles
        m5 = _make_m5_candles(count=220, start=start, start_price=1.1, step=0.0002)
        candles = _make_candle_objs(m5)
        trend_candles = candles
        entry_candles = candles[-120:]

        primitives = compute_primitives(
            trend_candles=trend_candles,
            entry_candles=entry_candles,
            trend_direction="flat",  # indicator-free structure will be used by detectors
            config={},
        )

        # Instantiate each registered detector class with enabled=True
        detector_names = detector_registry.list_detectors()
        if not detector_names:
            return _fail(name, "No detectors registered in engines.detectors")

        failures: List[str] = []
        for det_name in detector_names:
            det = detector_registry.create_detector(det_name, {"enabled": True})
            if det is None:
                failures.append(f"Could not instantiate {det_name}")
                continue

            result = det.detect(entry_candles, primitives, context={"pair": "EURUSD"})
            for f in required_fields:
                if not hasattr(result, f):
                    failures.append(f"{det_name}: missing field '{f}'")

            # Evidence must exist even if empty
            ev = getattr(result, "evidence", None)
            if ev is None or not isinstance(ev, list):
                failures.append(f"{det_name}: evidence is not a list")

        if failures:
            return _fail(name, "; ".join(failures[:8]))

        return _ok(name, f"Checked {len(detector_names)} detectors")
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def check_no_indicator_guard() -> CheckResult:
    name = "3) No-indicator guard (indicator-free modules)"
    forbidden = [
        "RSI",
        "MACD",
        "EMA",
        "SMA",
        "ATR",
        "Bollinger",
        "Ichimoku",
        "VWAP",
        "Stochastic",
        "ADX",
    ]
    # Scope guard to indicator-free modules only (legacy MA-based engine may exist elsewhere).
    include_paths: List[Path] = [
        Path("core") / "primitives.py",
        Path("build_basic_setup_v2.py"),
        Path("engines") / "detectors",
    ]

    pattern = re.compile(r"\\b(" + "|".join(re.escape(w) for w in forbidden) + r")\\b", re.IGNORECASE)

    hits: List[str] = []

    def scan_file(p: Path) -> None:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return
        for i, line in enumerate(text.splitlines(), start=1):
            m = pattern.search(line)
            if m:
                hits.append(f"{p.as_posix()}:{i}:{m.group(1)}")
                if len(hits) >= 20:
                    return

    for p in include_paths:
        if p.is_dir():
            for f in p.rglob("*.py"):
                scan_file(f)
        elif p.is_file():
            scan_file(p)

    if hits:
        return _fail(name, "Forbidden keywords found: " + ", ".join(hits[:8]))

    return _ok(name)


def check_determinism_signal_key() -> CheckResult:
    name = "4) Determinism (signal_key)"
    try:
        from core.user_core_engine import scan_pair_cached_indicator_free
        from signals_tracker import _make_signal_key

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        # Create an oscillating uptrend so fractal swings exist (required by structure trend).
        m5: List[Dict[str, Any]] = []
        base = 1.1000
        for i in range(320):
            t = start + timedelta(minutes=5 * i)
            drift = i * 0.00015
            wave = math.sin(i / 3.0) * 0.0006
            open_p = base + drift + wave
            close_p = open_p + 0.00008
            high_p = max(open_p, close_p) + 0.00025
            low_p = min(open_p, close_p) - 0.00025
            m5.append({"time": t, "open": open_p, "high": high_p, "low": low_p, "close": close_p})

        candles = _make_candle_objs(m5)

        profile = {
            "trend_tf": "H4",
            "entry_tf": "M15",
            "min_rr": 1.2,
            "engine_version": "indicator_free_v1",
            "detectors": {"structure_trend": {"enabled": True}},
            "primitives_config": {"fractal_left_bars": 2, "fractal_right_bars": 2},
        }

        r1 = scan_pair_cached_indicator_free("EURUSD", profile, candles, candles[-120:])
        r2 = scan_pair_cached_indicator_free("EURUSD", profile, candles, candles[-120:])

        if not r1.has_setup or r1.setup is None:
            return _fail(name, f"No setup produced for determinism check: {r1.reasons}")
        if not r2.has_setup or r2.setup is None:
            return _fail(name, f"No setup produced on second run: {r2.reasons}")

        fixed_iso = datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat()
        k1 = _make_signal_key(
            user_id="qa",
            pair="EURUSD",
            direction=str(r1.setup.direction),
            timeframe=str(profile.get("entry_tf", "M15")),
            entry=float(r1.setup.entry),
            sl=float(r1.setup.sl),
            tp=float(r1.setup.tp),
            generated_at_iso=fixed_iso,
        )
        k2 = _make_signal_key(
            user_id="qa",
            pair="EURUSD",
            direction=str(r2.setup.direction),
            timeframe=str(profile.get("entry_tf", "M15")),
            entry=float(r2.setup.entry),
            sl=float(r2.setup.sl),
            tp=float(r2.setup.tp),
            generated_at_iso=fixed_iso,
        )

        if k1 != k2:
            return _fail(name, "signal_key differs between identical runs")

        return _ok(name, f"signal_key={k1[:10]}...")
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def check_dedupe_cooldown() -> CheckResult:
    name = "5) Dedupe cooldown blocks resend"
    try:
        from services.models import SignalEvent
        from services.notifier_telegram import TelegramNotifier

        notifier = TelegramNotifier(token="TEST_TOKEN", default_chat_id=1)

        # Monkeypatch network methods so first send succeeds and history is recorded.
        notifier.send_message = lambda *args, **kwargs: True  # type: ignore[assignment]
        notifier.send_photo = lambda *args, **kwargs: True  # type: ignore[assignment]

        now = datetime.utcnow()
        sig = SignalEvent(
            pair="EURUSD",
            direction="BUY",
            timeframe="M15",
            entry=1.2345,
            sl=1.2300,
            tp=1.2450,
            rr=2.33,
            generated_at=now,
            reasons=["QA"],
        )

        ok1 = notifier.send_signal(sig)
        if not ok1:
            return _fail(name, "First send should succeed (mocked)")

        sig2 = SignalEvent(
            pair="EURUSD",
            direction="BUY",
            timeframe="M15",
            entry=1.2345,  # same entry => should dedupe
            sl=1.2300,
            tp=1.2450,
            rr=2.33,
            generated_at=now + timedelta(seconds=1),
            reasons=["QA"],
        )

        ok2 = notifier.send_signal(sig2)
        if ok2:
            return _fail(name, "Second send should be blocked by dedupe window")

        return _ok(name)
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def check_provider_contract_simulation() -> CheckResult:
    name = "6) Provider contract (simulation candles)"
    try:
        from data_providers.simulation_provider import SimulationDataProvider
        from data_providers.models import validate_candles

        p = SimulationDataProvider()
        candles = p.fetch_candles("EURUSD", timeframe="m5", max_count=200)
        if not candles:
            return _fail(name, "Simulation provider returned empty candles")

        try:
            validate_candles(candles)
        except Exception as e:
            return _fail(name, f"Contract violation: {e}")

        return _ok(name)
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def check_range_regime_trend_gate() -> CheckResult:
    name = "7) Range regime trend gate"
    try:
        from engine_blocks import Candle
        from core.user_core_engine import scan_pair_cached_indicator_free

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        support = 1.0000
        resistance = 1.0100

        candles: List[Candle] = []
        for i in range(140):
            t = start + timedelta(minutes=5 * i)
            phase = i % 20
            if phase < 10:
                price = support + (resistance - support) * (phase / 10.0)
            else:
                price = resistance - (resistance - support) * ((phase - 10) / 10.0)
            if i == 139:
                price = support * 1.0003

            candles.append(
                Candle(
                    time=t,
                    open=price,
                    high=price + 0.0004,
                    low=price - 0.0004,
                    close=price,
                )
            )

        entry = candles[-120:]

        base_profile = {
            "trend_tf": "H4",
            "entry_tf": "M15",
            "min_rr": 1.2,
            "engine_version": "indicator_free_v1",
            "detectors": {"range_box_edge": {"enabled": True}},
            # Force structure trend to be "unclear" (no fractal swings)
            "primitives_config": {"fractal_left_bars": 90, "fractal_right_bars": 90},
        }

        p1 = dict(base_profile)
        p1["require_clear_trend_for_signal"] = False
        r1 = scan_pair_cached_indicator_free("EURUSD", p1, candles, entry)
        if not (r1.has_setup and r1.setup is not None):
            return _fail(name, f"Expected setup in range regime when gate disabled: {r1.reasons}")
        if "TREND_UNCLEAR_REGIME_FALLBACK" not in (r1.reasons or []):
            return _fail(name, f"Missing TREND_UNCLEAR_REGIME_FALLBACK reason: {r1.reasons}")
        if not any(r.startswith("REGIME|") for r in (r1.reasons or [])):
            return _fail(name, f"Missing REGIME|* reason: {r1.reasons}")

        p2 = dict(base_profile)
        p2["require_clear_trend_for_signal"] = True
        r2 = scan_pair_cached_indicator_free("EURUSD", p2, candles, entry)
        if r2.has_setup:
            return _fail(name, "Expected no setup when require_clear_trend_for_signal=True")
        if not r2.reasons or r2.reasons[0] != "TREND_UNCLEAR_REGIME_FALLBACK":
            return _fail(name, f"Expected first reason TREND_UNCLEAR_REGIME_FALLBACK: {r2.reasons}")

        return _ok(name)
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def check_regime_filters_trend_only_detectors() -> CheckResult:
    name = "9) Regime filters trend-only detectors"
    try:
        from engine_blocks import Candle
        from core.user_core_engine import scan_pair_cached_indicator_free

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        candles: List[Candle] = []
        # Flat-ish candles so structure trend is unclear => regime CHOP.
        price = 1.1000
        for i in range(140):
            t = start + timedelta(minutes=5 * i)
            price = price + (0.00002 if i % 2 == 0 else -0.00002)
            candles.append(
                Candle(
                    time=t,
                    open=price,
                    high=price + 0.0002,
                    low=price - 0.0002,
                    close=price,
                )
            )

        profile = {
            "trend_tf": "H4",
            "entry_tf": "M15",
            "min_rr": 1.2,
            "engine_version": "indicator_free_v1",
            "require_clear_trend_for_signal": False,
            # structure_trend is TREND_* only; should be skipped under CHOP.
            "detectors": {"structure_trend": {"enabled": True}},
            "primitives_config": {"fractal_left_bars": 90, "fractal_right_bars": 90},
        }

        res = scan_pair_cached_indicator_free("EURUSD", profile, candles, candles[-120:])
        if res.has_setup:
            return _fail(name, "Expected no setup when only trend-only detector is enabled under CHOP")
        if not isinstance(res.debug, dict):
            return _fail(name, "Expected debug dict")
        skipped = res.debug.get("detectors_skipped_regime")
        if not (isinstance(skipped, list) and "structure_trend" in skipped):
            return _fail(name, f"Expected structure_trend to be skipped by regime filter: {skipped}")

        return _ok(name)
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def check_soft_combine_conflict_score() -> CheckResult:
    name = "10) Soft-combine conflict scoring"
    try:
        from engines.detectors.base import BaseDetector, DetectorResult
        from engines.detectors.registry import detector_registry
        from core.user_core_engine import scan_pair_cached_indicator_free

        # Register two deterministic QA detectors (BUY and SELL) that always match.
        class QABuyDetector(BaseDetector):
            name = "qa_buy"
            family = "sr"

            def detect(self, candles, primitives, context=None) -> DetectorResult:
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction="BUY",
                    confidence=0.90,
                    evidence=["QA_BUY"],
                    tags=["sr"],
                    score_contrib=0.90,
                )

        class QASellDetector(BaseDetector):
            name = "qa_sell"
            family = "range"

            def detect(self, candles, primitives, context=None) -> DetectorResult:
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction="SELL",
                    confidence=0.90,
                    evidence=["QA_SELL"],
                    tags=["range"],
                    score_contrib=0.90,
                )

        detector_registry.register(QABuyDetector)
        detector_registry.register(QASellDetector)

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        m5 = _make_m5_candles(count=220, start=start, start_price=1.1, step=0.00005)
        candles = _make_candle_objs(m5)
        entry = candles[-120:]

        profile = {
            "trend_tf": "H4",
            "entry_tf": "M15",
            "min_rr": 1.2,
            "engine_version": "indicator_free_v1",
            "detectors": {"qa_buy": {"enabled": True}, "qa_sell": {"enabled": True}},
            "min_score": 0.50,
            "conflict_score_delta": 0.25,
            "confluence_weight": 0.00,
        }

        res = scan_pair_cached_indicator_free("EURUSD", profile, candles, entry)
        if res.has_setup:
            return _fail(name, "Expected no setup due to CONFLICT_SCORE")
        if not res.reasons or res.reasons[0] != "CONFLICT_SCORE":
            return _fail(name, f"Expected CONFLICT_SCORE, got: {res.reasons}")
        if not isinstance(res.debug, dict) or "conflict" not in res.debug:
            return _fail(name, "Expected debug.conflict to be present")

        return _ok(name)
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def check_setup_builder_rr_below_min_evidence() -> CheckResult:
    name = "8) Setup builder RR_BELOW_MIN evidence"
    try:
        from build_basic_setup_v2 import RR_BELOW_MIN, BuildSetupResult, build_basic_setup_v2
        from core.primitives import (
            FibLevelResult,
            PrimitiveResults,
            SRZone,
            SRZoneResult,
            SwingResult,
            TrendStructureResult,
        )

        # Construct primitives so RR < min_rr.
        # With edge-entry enabled: SELL entry snaps to resistance.high (=101.0),
        # SL becomes zone.high + buffer (buffer = 25% zone_width_abs => 0.3), so risk~0.3.
        # Put the only support target very close (100.9) so reward~0.1 and RR~0.33 (< 1.2).
        entry = 100.95
        primitives = PrimitiveResults(
            swing=SwingResult(swing=None, direction="flat", found=False),
            sr_zones=SRZoneResult(support=100.9, resistance=101.0, last_close=entry),
            trend_structure=TrendStructureResult(direction="flat", structure_valid=False),
            fib_levels=FibLevelResult(retrace={}, extensions={}, swing=None),
            sr_zones_clustered=[
                SRZone(level=101.0, lower=99.8, upper=101.0, strength=3, is_resistance=True),
                SRZone(level=100.9, lower=100.85, upper=100.95, strength=3, is_resistance=False),
            ],
        )

        res: BuildSetupResult = build_basic_setup_v2(
            pair="EURUSD",
            direction="SELL",
            entry_price=entry,
            primitives=primitives,
            min_rr=1.2,
            profile={},
        )

        if res.ok:
            return _fail(name, "Expected builder to fail RR_BELOW_MIN, but ok=True")
        if res.fail_reason != RR_BELOW_MIN:
            return _fail(name, f"Expected fail_reason={RR_BELOW_MIN}, got {res.fail_reason}")
        if not isinstance(res.evidence, dict) or not res.evidence:
            return _fail(name, "Evidence dict missing/empty")

        # Evidence must include at least these fields when RR is computed.
        for k in ("rr", "min_rr", "sl_dist", "tp_dist", "entry_zone"):
            if k not in res.evidence:
                return _fail(name, f"Evidence missing key '{k}'")

        return _ok(name)
    except Exception as e:
        return _fail(name, f"Exception: {e}")


def main() -> int:
    checks: List[Callable[[], CheckResult]] = [
        check_cache_memoization,
        check_detector_contract,
        check_no_indicator_guard,
        check_determinism_signal_key,
        check_dedupe_cooldown,
        check_provider_contract_simulation,
        check_range_regime_trend_gate,
        check_setup_builder_rr_below_min_evidence,
        check_regime_filters_trend_only_detectors,
        check_soft_combine_conflict_score,
    ]

    results: List[CheckResult] = []
    for chk in checks:
        res = chk()
        results.append(res)
        status = "PASS" if res.ok else "FAIL"
        msg = f"[{status}] {res.name}"
        if res.detail:
            msg += f" :: {res.detail}"
        print(msg)

    failed = [r for r in results if not r.ok]
    if failed:
        print("\nFAILED CHECKS:")
        for r in failed:
            print(f"- {r.name}: {r.detail}")
        return 1

    print("\nALL QA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
