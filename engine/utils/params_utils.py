from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple


def _stable_json(obj: Any) -> str:
    """Stable JSON encoding for hashing/diffing.

    - sort_keys=True for stability
    - separators to avoid whitespace drift
    - ensure_ascii=True for consistent bytes
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def stable_params_digest(obj: Any, *, length: int = 10) -> str:
    """Return a short stable digest for params payload."""
    s = _stable_json(obj)
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return h[: max(4, int(length))]


def sanitize_params(
    value: Any,
    *,
    max_keys: int = 30,
    max_depth: int = 3,
    max_list_len: int = 30,
    max_str_len: int = 200,
) -> Tuple[Any, bool]:
    """Best-effort sanitize/truncate params to keep logs/objects safe.

    Returns:
        (sanitized, truncated)

    Notes:
    - Only dict/list/str primitives are truncated.
    - Other values are passed through as-is.
    """
    truncated = False

    if max_depth <= 0:
        return "<max_depth>", True

    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        items = list(value.items())
        if len(items) > int(max_keys):
            items = items[: int(max_keys)]
            truncated = True
        for k, v in items:
            ks = str(k)
            vv, t = sanitize_params(
                v,
                max_keys=max_keys,
                max_depth=max_depth - 1,
                max_list_len=max_list_len,
                max_str_len=max_str_len,
            )
            truncated = truncated or t
            out[ks] = vv
        return out, truncated

    if isinstance(value, (list, tuple)):
        items2 = list(value)
        if len(items2) > int(max_list_len):
            items2 = items2[: int(max_list_len)]
            truncated = True
        out_list: List[Any] = []
        for x in items2:
            xx, t = sanitize_params(
                x,
                max_keys=max_keys,
                max_depth=max_depth - 1,
                max_list_len=max_list_len,
                max_str_len=max_str_len,
            )
            truncated = truncated or t
            out_list.append(xx)
        return out_list, truncated

    if isinstance(value, str):
        if len(value) > int(max_str_len):
            return value[: int(max_str_len)], True
        return value, False

    return value, False


def merge_param_layers(
    *,
    base: Dict[str, Any],
    family: Dict[str, Any],
    detector: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge params with precedence: base < family < detector."""
    out: Dict[str, Any] = {}
    for layer in (base, family, detector):
        if isinstance(layer, dict):
            for k, v in layer.items():
                if str(k) == "enabled":
                    # Reserved key; do not allow params to flip enabled.
                    continue
                out[str(k)] = v
    return out
