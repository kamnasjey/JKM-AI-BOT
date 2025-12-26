"""core.ops

Ops helpers: startup banner + health snapshot.

- Keep deterministic + NA-safe fields.
- Avoid heavy imports at module import time.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from engine.utils.logging_utils import log_kv, log_kv_warning

from core.version import (
    APP_VERSION,
    EXPLAIN_SCHEMA_VERSION,
    GIT_SHA,
    METRICS_EVENT_SCHEMA_VERSION,
    STRATEGY_SCHEMA_VERSION_SUPPORTED,
)

_PROCESS_START_TS: float = time.time()


def _na_str(v: Any) -> str:
    s = "" if v is None else str(v)
    s = s.strip()
    return s if s else "NA"


def _safe_int(v: Any) -> Optional[int]:
    try:
        i = int(v)
    except Exception:
        return None
    return i


def _safe_file_size(path: str) -> Any:
    p = str(path or "").strip()
    if not p:
        return "NA"
    try:
        return int(os.path.getsize(p))
    except Exception:
        return "NA"


def uptime_s(now_ts: Optional[float] = None) -> int:
    now = float(time.time() if now_ts is None else now_ts)
    dt = now - float(_PROCESS_START_TS)
    if dt < 0:
        dt = 0.0
    return int(dt)


def log_startup_banner(
    logger,
    *,
    presets_dir: str = "config/presets",
    notify_mode: Optional[str] = None,
    provider: Optional[str] = None,
) -> None:
    """Emit one-line startup banner.

    Format (contract):
      STARTUP_BANNER | app_version=... | git_sha=... | strategy_schema=1 | ...
    """
    detectors_count = 0
    try:
        from engines.detectors.registry import detector_registry, ensure_registry_loaded

        ensure_registry_loaded(logger=logger, custom_dir="detectors/custom")
        detectors_count = int(getattr(detector_registry, "count", lambda: 0)())
        if detectors_count <= 0:
            # Critical misconfiguration; allow fail-fast via STRICT_STARTUP.
            log_kv_warning(
                logger,
                "STARTUP_WARN",
                code="NO_DETECTORS_LOADED",
                severity="critical",
            )
            strict = str(os.getenv("STRICT_STARTUP", "0") or "0").strip().lower()
            if strict in ("1", "true", "yes", "y", "on"):
                raise RuntimeError("NO_DETECTORS_LOADED")
    except RuntimeError:
        raise
    except Exception:
        detectors_count = int(detectors_count or 0)

    try:
        import config as _cfg

        nm = notify_mode if notify_mode is not None else getattr(_cfg, "NOTIFY_MODE", None)
        pv = provider if provider is not None else getattr(_cfg, "MARKET_DATA_PROVIDER", None)
    except Exception:
        nm = notify_mode
        pv = provider

    schema = STRATEGY_SCHEMA_VERSION_SUPPORTED[0] if STRATEGY_SCHEMA_VERSION_SUPPORTED else 1

    shadow_all = str(os.getenv("SHADOW_ALL_DETECTORS", "")).strip()
    shadow_all = "1" if shadow_all == "1" else "0"

    log_kv(
        logger,
        "STARTUP_BANNER",
        app_version=_na_str(APP_VERSION),
        git_sha=_na_str(GIT_SHA),
        strategy_schema=int(schema),
        explain_schema=int(EXPLAIN_SCHEMA_VERSION),
        metrics_schema=int(METRICS_EVENT_SCHEMA_VERSION),
        detectors=int(detectors_count),
        shadow_all_detectors=_na_str(shadow_all),
        presets_dir=_na_str(presets_dir),
        notify_mode=_na_str(nm),
        provider=_na_str(pv),
    )


def build_health_snapshot(
    *,
    scanner: Any = None,
    strategies_path: str = "config/strategies.json",
    presets_dir: str = "config/presets",
    metrics_events_path: str = "state/metrics_events.jsonl",
    patch_audit_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a deterministic, NA-safe JSON dict for ops health."""

    audit_path = patch_audit_path or os.getenv("PATCH_AUDIT_PATH", "state/patch_audit.jsonl")

    # Strategy pack diagnostics (best-effort; never raise)
    strategies_loaded_count = "NA"
    invalid_strategies: Any = []
    unknown_detectors_count: Any = "NA"

    try:
        from strategies.loader import load_strategy_pack

        pack = load_strategy_pack(strategies_path, presets_dir=presets_dir)
        strategies_loaded_count = int(len(getattr(pack, "strategies", []) or []))
        invalid_items = list(getattr(pack, "invalid_enabled", []) or [])
        invalid_strategies = [str(x.get("strategy_id") or "").strip() for x in invalid_items if isinstance(x, dict)]
        invalid_strategies = [x for x in invalid_strategies if x]

        unknown_by = getattr(pack, "unknown_detectors_by_strategy", {}) or {}
        unknown_set = set()
        if isinstance(unknown_by, dict):
            for _, names in unknown_by.items():
                if isinstance(names, list):
                    for n in names:
                        nn = str(n or "").strip()
                        if nn:
                            unknown_set.add(nn)
        unknown_detectors_count = int(len(sorted(unknown_set)))
    except Exception:
        # Keep NA-safe defaults.
        pass

    last_scan_ts = "NA"
    last_scan_id = "NA"
    try:
        if scanner is not None and hasattr(scanner, "get_last_scan_info"):
            info = scanner.get_last_scan_info() or {}
            if isinstance(info, dict):
                last_scan_ts = _na_str(info.get("last_scan_ts"))
                last_scan_id = _na_str(info.get("last_scan_id"))
    except Exception:
        pass

    out: Dict[str, Any] = {
        "status": "ok",
        "app_version": _na_str(APP_VERSION),
        "git_sha": _na_str(GIT_SHA),
        "uptime_s": int(uptime_s()),
        "strategies_loaded_count": strategies_loaded_count,
        "invalid_strategies": invalid_strategies,
        "unknown_detectors_count": unknown_detectors_count,
        "last_scan_ts": last_scan_ts,
        "last_scan_id": last_scan_id,
        "metrics_events_file_size": _safe_file_size(metrics_events_path),
        "patch_audit_file_size": _safe_file_size(audit_path),
    }

    # Deterministic: ensure json-serializable (best-effort).
    try:
        json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        out["status"] = "error"

    # Mark degraded if invalid strategies are present.
    try:
        if isinstance(invalid_strategies, list) and len(invalid_strategies) > 0:
            out["status"] = "degraded"
    except Exception:
        pass

    # Add timestamp (non-required but useful)?? NO: keep exactly requested keys.
    return out


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
