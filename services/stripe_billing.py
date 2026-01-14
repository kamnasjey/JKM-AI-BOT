from __future__ import annotations

import hmac
import json
import time
from hashlib import sha256
from typing import Any, Optional

import httpx


class StripeError(RuntimeError):
    pass


def create_checkout_session(
    *,
    stripe_secret_key: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    customer_email: Optional[str],
    client_reference_id: str,
    metadata: dict[str, str],
) -> dict[str, Any]:
    if not stripe_secret_key:
        raise StripeError("STRIPE_SECRET_KEY missing")
    if not price_id:
        raise StripeError("price_id missing")

    # Stripe expects application/x-www-form-urlencoded.
    data: dict[str, Any] = {
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": client_reference_id,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": 1,
    }

    if customer_email:
        data["customer_email"] = customer_email

    for k, v in (metadata or {}).items():
        if k and v is not None:
            data[f"metadata[{k}]"] = str(v)
            # Also attach to the underlying subscription so we can handle
            # customer.subscription.* webhooks without a DB lookup.
            data[f"subscription_data[metadata][{k}]"] = str(v)

    headers = {
        "Authorization": f"Bearer {stripe_secret_key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    with httpx.Client(timeout=20.0) as client:
        r = client.post("https://api.stripe.com/v1/checkout/sessions", data=data, headers=headers)

    if r.status_code >= 400:
        try:
            payload = r.json()
        except Exception:
            payload = {"raw": r.text}
        raise StripeError(f"Stripe error {r.status_code}: {payload}")

    return r.json()


def _parse_stripe_sig(sig_header: str) -> tuple[Optional[int], list[str]]:
    if not sig_header:
        return None, []
    parts = [p.strip() for p in sig_header.split(",") if p.strip()]
    ts: Optional[int] = None
    v1: list[str] = []
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "t":
            try:
                ts = int(v)
            except Exception:
                ts = None
        elif k == "v1":
            v1.append(v)
    return ts, v1


def verify_webhook_signature(
    *,
    payload_bytes: bytes,
    stripe_signature_header: str,
    webhook_secret: str,
    tolerance_s: int = 300,
) -> bool:
    if not webhook_secret:
        return False

    ts, sigs = _parse_stripe_sig(stripe_signature_header)
    if ts is None or not sigs:
        return False

    now = int(time.time())
    if abs(now - int(ts)) > int(tolerance_s):
        return False

    signed_payload = f"{ts}.".encode("utf-8") + payload_bytes
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, sha256).hexdigest()

    for s in sigs:
        if hmac.compare_digest(expected, s):
            return True
    return False


def parse_event(payload_bytes: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        raise StripeError(f"invalid JSON: {e}")
    if not isinstance(obj, dict):
        raise StripeError("invalid event")
    return obj
