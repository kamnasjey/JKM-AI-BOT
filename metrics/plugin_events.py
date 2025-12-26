from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


_LOCK = threading.Lock()


def _safe_str(v: Any) -> str:
    s = str(v if v is not None else "NA").strip()
    return s if s else "NA"


def _safe_jsonable(obj: Any, *, depth: int = 0, max_depth: int = 4, max_list: int = 50) -> Any:
    if depth > max_depth:
        return "..."

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in list(obj.items())[: int(max_list)]:
            out[_safe_str(k)] = _safe_jsonable(v, depth=depth + 1, max_depth=max_depth, max_list=max_list)
        return out

    if isinstance(obj, (list, tuple)):
        return [
            _safe_jsonable(x, depth=depth + 1, max_depth=max_depth, max_list=max_list)
            for x in list(obj)[: int(max_list)]
        ]

    return _safe_str(obj)


@dataclass(frozen=True)
class PluginEvent:
    ts: float
    event: str
    scan_id: str
    detector: str
    message: str
    extra: Optional[Any] = None
    flags: Optional[Any] = None
    schema_version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schema_version": int(self.schema_version),
            "ts": float(self.ts),
            "event": _safe_str(self.event),
            "scan_id": _safe_str(self.scan_id),
            "detector": _safe_str(self.detector),
            "message": _safe_str(self.message),
        }
        if self.extra is not None:
            out["extra"] = _safe_jsonable(self.extra)
        if self.flags is not None:
            out["flags"] = _safe_jsonable(self.flags)
        return out


def emit_plugin_event(
    event: PluginEvent,
    *,
    path: str = "state/plugin_events.jsonl",
) -> None:
    """Append one plugin event JSONL line. Non-fatal by design."""
    try:
        from core.atomic_io import atomic_append_jsonl_via_replace

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        line = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with _LOCK:
            atomic_append_jsonl_via_replace(Path(path), line)
    except Exception:
        return


def emit_plugin_event_now(
    *,
    event: str,
    scan_id: str = "NA",
    detector: str = "NA",
    message: str = "",
    extra: Optional[Any] = None,
    flags: Optional[Any] = None,
    path: str = "state/plugin_events.jsonl",
) -> None:
    emit_plugin_event(
        PluginEvent(
            ts=float(time.time()),
            event=str(event or "NA"),
            scan_id=str(scan_id or "NA"),
            detector=str(detector or "NA"),
            message=str(message or ""),
            extra=extra,
            flags=flags,
        ),
        path=str(path),
    )
