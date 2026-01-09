from __future__ import annotations

import types

import scripts.backfill_massive as backfill


def test_backfill_cli_accepts_tf_alias(monkeypatch):
    called = {"ok": False, "timeframe": None}

    def fake_run_backfill(**kwargs):
        called["ok"] = True
        called["timeframe"] = kwargs.get("timeframe")
        return 0

    monkeypatch.setattr(backfill, "run_backfill", fake_run_backfill)

    rc = backfill.main(["--symbols", "EURUSD", "--days", "7", "--tf", "m5", "--chunk-days", "7"])
    assert rc == 0
    assert called["ok"] is True
    assert str(called["timeframe"]).lower() in {"m5", "5m"}


def test_backfill_cli_accepts_timeframe(monkeypatch):
    called = {"ok": False, "timeframe": None}

    def fake_run_backfill(**kwargs):
        called["ok"] = True
        called["timeframe"] = kwargs.get("timeframe")
        return 0

    monkeypatch.setattr(backfill, "run_backfill", fake_run_backfill)

    rc = backfill.main(["--symbols", "EURUSD", "--days", "7", "--timeframe", "m5", "--chunk-days", "7"])
    assert rc == 0
    assert called["ok"] is True
    assert str(called["timeframe"]).lower() in {"m5", "5m"}
