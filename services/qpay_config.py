from __future__ import annotations

import json
import os
from typing import Any, Optional


def get_qpay_amount_for_plan(plan_id: str) -> int:
    pid = str(plan_id or "").strip().lower()
    if pid == "pro":
        return int(os.getenv("QPAY_AMOUNT_PRO") or "0")
    if pid in {"pro_plus", "pro+"}:
        return int(os.getenv("QPAY_AMOUNT_PRO_PLUS") or "0")
    return 0


def get_qpay_extra_payload() -> Optional[dict[str, Any]]:
    raw = (os.getenv("QPAY_INVOICE_EXTRA_JSON") or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj
