from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

from metrics.alert_codes import canonicalize_alert_code


_LOCK = threading.Lock()


def load_alert_state(path: str = "state/metrics_alert_state.json") -> Dict[str, Any]:
    """Load persisted metrics alert state. Non-fatal; returns empty state on errors."""
    with _LOCK:
        if not os.path.exists(path):
            return {"schema": 1, "alerts": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            return {"schema": 1, "alerts": {}}

    if not isinstance(data, dict):
        return {"schema": 1, "alerts": {}}

    alerts = data.get("alerts")
    if not isinstance(alerts, dict):
        alerts = {}

    # Migrate legacy keys to canonical codes.
    migrated: Dict[str, Any] = {}
    for k, v in alerts.items():
        canon = canonicalize_alert_code(str(k))
        if canon == "NA":
            continue
        # If both legacy and canonical exist, prefer the canonical entry.
        if canon in migrated and str(k).upper() != canon:
            continue
        migrated[canon] = v

    return {"schema": int(data.get("schema") or 1), "alerts": migrated}


def save_alert_state_atomic(state: Dict[str, Any], path: str = "state/metrics_alert_state.json") -> None:
    """Atomic save: write temp file then replace."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    tmp_path = f"{path}.tmp"
    payload = state if isinstance(state, dict) else {"schema": 1, "alerts": {}}

    with _LOCK:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
