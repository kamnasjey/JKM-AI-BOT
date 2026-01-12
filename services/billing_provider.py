from __future__ import annotations

import os


def get_billing_provider() -> str:
    """Return the active billing provider.

    Supported: "manual", "qpay", "stripe".

    Defaults to manual bank-transfer approval flow.
    """

    provider = str(os.getenv("BILLING_PROVIDER") or "manual").strip().lower()
    if provider in {"manual", "qpay", "stripe"}:
        return provider
    return "manual"
