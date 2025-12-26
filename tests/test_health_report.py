from __future__ import annotations

import io
import logging

from core.ops import build_health_snapshot, log_startup_banner


def test_startup_banner_contains_versions() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("test_startup_banner")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False
    logger.addHandler(handler)

    log_startup_banner(logger, presets_dir="config/presets", notify_mode="all", provider="simulation")

    out = stream.getvalue()
    assert "STARTUP_BANNER" in out
    assert "app_version=" in out
    assert "git_sha=" in out
    assert "strategy_schema=" in out
    assert "explain_schema=" in out
    assert "metrics_schema=" in out


def test_health_report_json_keys_present(tmp_path) -> None:
    strategies_path = tmp_path / "strategies.json"
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir(parents=True, exist_ok=True)

    # Minimal v1 strategy pack.
    strategies_path.write_text('{"schema_version":1,"strategies":[]}', encoding="utf-8")

    metrics_events_path = tmp_path / "metrics_events.jsonl"
    metrics_events_path.write_text("{}\n", encoding="utf-8")

    patch_audit_path = tmp_path / "patch_audit.jsonl"
    patch_audit_path.write_text("{}\n", encoding="utf-8")

    payload = build_health_snapshot(
        scanner=None,
        strategies_path=str(strategies_path),
        presets_dir=str(presets_dir),
        metrics_events_path=str(metrics_events_path),
        patch_audit_path=str(patch_audit_path),
    )

    expected_keys = {
        "status",
        "app_version",
        "git_sha",
        "uptime_s",
        "strategies_loaded_count",
        "invalid_strategies",
        "unknown_detectors_count",
        "last_scan_ts",
        "last_scan_id",
        "metrics_events_file_size",
        "patch_audit_file_size",
    }

    assert expected_keys.issubset(set(payload.keys()))
    # NA-safe: no None values.
    assert all(v is not None for v in payload.values())
