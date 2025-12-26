"""One-shot measurement for cache-first architecture.

Goal:
- Show how many IG HTTP requests happen during ingestion (provider.get_candles).
- Show that running the scan/analysis from cached candles causes *zero* additional IG HTTP requests.

This does not require the web app; it runs as a CLI script.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from ig_client import get_ig_request_stats, ig_call_source, IGClient


def _safe_json(obj):
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


def main() -> None:
    # 1) Reset stats and init client (counts login traffic)
    print("RESET", _safe_json(get_ig_request_stats(reset=True)))

    ig_ok = False
    provider_ok = False
    try:
        from providers.ig_provider import IGProvider

        ig = IGClient.from_env()
        provider = IGProvider(ig)
        ig_ok = True
        provider_ok = True
    except Exception as exc:
        print("IG_INIT_FAILED", repr(exc))
        provider = None

    # 2) Attempt an ingestion-like fetch (tagged as source=ingestor)
    fetched = 0
    if provider is not None:
        try:
            with ig_call_source("ingestor"):
                candles = provider.get_candles("EURUSD", timeframe="m5", limit=200)
            fetched = len(candles or [])
        except Exception as exc:
            print("INGEST_FETCH_FAILED", repr(exc))

    snap_after_ingest = get_ig_request_stats()

    # 3) Run scan logic using cached candles (no IG)
    # If we couldn't fetch from IG, fall back to simulation candles for the scan step.
    try:
        from market_data_cache import market_cache
        from resample_5m import resample
        from engine_blocks import Candle
        from user_core_engine import scan_pair_cached

        symbol = "EURUSD"

        if fetched:
            raw_5m = market_cache.get_candles(symbol)
        else:
            from providers.simulation_provider import SimulationProvider

            sim = SimulationProvider()
            raw_5m = sim.get_candles(symbol, timeframe="m5", limit=500)
            market_cache.upsert_candles(symbol, raw_5m)

        trend_tf = "H4"
        entry_tf = "M15"
        trend_data = resample(raw_5m, trend_tf)
        entry_data = resample(raw_5m, entry_tf)

        def to_candles(items):
            out = []
            for d in items:
                out.append(
                    Candle(
                        time=d["time"],
                        open=float(d["open"]),
                        high=float(d["high"]),
                        low=float(d["low"]),
                        close=float(d["close"]),
                    )
                )
            return out

        profile = {
            "user_id": "measure",
            "watch_pairs": [symbol],
            "trend_tf": trend_tf,
            "entry_tf": entry_tf,
            "min_rr": 2.0,
            "risk_percent": 1.0,
            "use_fib": True,
            "use_sr": True,
        }

        result = scan_pair_cached(symbol, profile, to_candles(trend_data), to_candles(entry_data))
        scan_summary = {
            "has_setup": bool(getattr(result, "has_setup", False)),
            "reasons": getattr(result, "reasons", []),
        }
    except Exception as exc:
        scan_summary = {"error": repr(exc)}

    snap_after_scan = get_ig_request_stats()

    # 4) Compute delta
    def delta(a: dict, b: dict) -> dict:
        return {
            "total": int(b.get("total", 0)) - int(a.get("total", 0)),
            "by_source": {
                k: int((b.get("by_source", {}) or {}).get(k, 0))
                - int((a.get("by_source", {}) or {}).get(k, 0))
                for k in set((a.get("by_source", {}) or {}).keys()) | set((b.get("by_source", {}) or {}).keys())
            },
        }

    ingest_to_scan_delta = delta(snap_after_ingest, snap_after_scan)
    ingest_to_scan_delta["by_source"] = {k: v for k, v in ingest_to_scan_delta["by_source"].items() if v}

    report = {
        "ig_init_ok": ig_ok,
        "provider_ok": provider_ok,
        "fetched_candles_from_ig": fetched,
        "stats_after_ingest": snap_after_ingest,
        "scan_summary": scan_summary,
        "stats_after_scan": snap_after_scan,
        "delta_scan_vs_after_ingest": ingest_to_scan_delta,
        "expected": "delta_scan_vs_after_ingest.total should be 0 (scan uses cache; no IG HTTP)"
    }

    print("REPORT", _safe_json(report))


if __name__ == "__main__":
    main()
