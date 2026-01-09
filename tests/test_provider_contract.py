from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data_providers.simulation_provider import SimulationDataProvider
from data_providers.normalize import normalize_candles
from data_providers.models import Candle, validate_candles
from data_providers.massive_provider import to_massive_ticker


def _assert_contract(candles):
    assert isinstance(candles, list)
    assert candles, "expected non-empty candles"
    assert all(isinstance(c, Candle) for c in candles)

    times = [c.ts for c in candles]
    assert all(isinstance(t, datetime) for t in times)
    assert all(t.tzinfo is not None for t in times)
    assert all(t.tzinfo == timezone.utc for t in times)

    validate_candles(candles)


def test_simulation_provider_contract():
    p = SimulationDataProvider()
    candles = p.fetch_candles("EURUSD", timeframe="m5", max_count=200)
    _assert_contract(candles)


def test_normalize_symbol_mappings_three_symbols():
    p = SimulationDataProvider()
    # Simulation provider uses canonical normalization.
    assert p.normalize_symbol("eur/usd") == "EURUSD"
    assert p.normalize_symbol("XAUUSD") == "XAUUSD"
    assert p.normalize_symbol(" btcusd ") == "BTCUSD"


def test_massive_ticker_mapping_three_symbols():
    assert to_massive_ticker("EURUSD") == "C:EURUSD"
    assert to_massive_ticker("XAUUSD") == "C:XAUUSD"
    assert to_massive_ticker("BTCUSD") == "X:BTCUSD"


def test_normalize_removes_duplicates_and_sorts():
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    raw = [
        {"time": base + timedelta(minutes=10), "open": 1, "high": 2, "low": 0.5, "close": 1.5},
        {"time": base, "open": 1, "high": 1.1, "low": 0.9, "close": 1.0},
        # duplicate timestamp (should be de-duped)
        {"time": base, "open": 1.0, "high": 1.2, "low": 0.8, "close": 1.1},
    ]
    out = normalize_candles(raw, provider="TEST", symbol="EURUSD", timeframe="m5", requested_limit=10)
    _assert_contract(out)
    assert out[0].ts == base
    assert len(out) == 2


@pytest.mark.skipif(
    pytest.importorskip("os").getenv("MASSIVE_PROVIDER_CONTRACT_TEST") not in ("1", "true", "yes"),
    reason="Massive provider contract test is opt-in (set MASSIVE_PROVIDER_CONTRACT_TEST=1)",
)
def test_massive_provider_contract_if_configured():
    # Optional: runs only when Massive env is configured.
    from data_providers.factory import create_provider

    import requests

    p = create_provider(name="massive")
    try:
        candles = p.fetch_candles("EURUSD", timeframe="m5", max_count=200)
    except requests.exceptions.HTTPError as e:
        raise

    _assert_contract(candles)
