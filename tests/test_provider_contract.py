from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data_providers.simulation_provider import SimulationDataProvider
from data_providers.normalize import normalize_candles
from data_providers.models import Candle, validate_candles
from data_providers.instruments import load_instruments_catalog, resolve_provider_symbol


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


def test_instruments_catalog_has_ig_mappings_for_three_symbols():
    catalog = load_instruments_catalog()
    assert resolve_provider_symbol(catalog, symbol="EURUSD", provider_name="IG") == "CS.D.EURUSD.MINI.IP"
    assert resolve_provider_symbol(catalog, symbol="XAUUSD", provider_name="IG") == "CS.D.CFDGOLD.CFDGC.IP"
    assert resolve_provider_symbol(catalog, symbol="BTCUSD", provider_name="IG") == "CS.D.BITCOIN.CFD.IP"


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
    pytest.importorskip("os").getenv("IG_PROVIDER_CONTRACT_TEST") not in ("1", "true", "yes"),
    reason="IG provider contract test is opt-in (set IG_PROVIDER_CONTRACT_TEST=1)",
)
def test_ig_provider_contract_if_configured():
    # Optional: runs only when IG env is configured.
    from data_providers.factory import create_provider

    import requests

    p = create_provider(name="ig")
    try:
        candles = p.fetch_candles("EURUSD", timeframe="m5", max_count=200)
    except requests.exceptions.HTTPError as e:
        # Demo environments often return 403 for /prices history; treat as a skip.
        resp = getattr(e, "response", None)
        if resp is not None and getattr(resp, "status_code", None) == 403:
            pytest.skip("IG /prices returned 403 (entitlement/allowance); skipping contract test")
        raise

    _assert_contract(candles)
