from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import httpx


class QPayError(RuntimeError):
    pass


@dataclass(frozen=True)
class QPayInvoice:
    invoice_id: Optional[str]
    payment_url: Optional[str]
    qr_text: Optional[str]
    qr_image: Optional[str]
    raw: dict[str, Any]


def _pick_payment_url(payload: dict[str, Any]) -> Optional[str]:
    # Common shapes we might see from QPay-style APIs.
    for key in ("payment_url", "checkout_url", "invoice_url", "url"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()

    urls = payload.get("urls")
    if isinstance(urls, list):
        for item in urls:
            if not isinstance(item, dict):
                continue
            link = item.get("link") or item.get("url")
            if isinstance(link, str) and link.strip():
                return link.strip()

    return None


def _extract_invoice_id(payload: dict[str, Any]) -> Optional[str]:
    for key in ("invoice_id", "id", "invoiceId", "invoice", "invoice_no"):
        v = payload.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def create_invoice(
    *,
    base_url: str,
    username: str,
    password: str,
    invoice_code: str,
    amount: int,
    description: str,
    reference_id: str,
    callback_url: Optional[str] = None,
    auth_url: Optional[str] = None,
    invoice_url: Optional[str] = None,
    extra_payload: Optional[dict[str, Any]] = None,
) -> QPayInvoice:
    """Create a QPay invoice.

    This is intentionally configurable via URLs/env so you can plug in the
    exact endpoints/fields you get from your QPay contract without rewriting
    app logic.
    """

    base = (base_url or "").rstrip("/")
    if not base:
        raise QPayError("QPAY_BASE_URL missing")
    if not username or not password:
        raise QPayError("QPAY_USERNAME/QPAY_PASSWORD missing")
    if not invoice_code:
        raise QPayError("QPAY_INVOICE_CODE missing")
    if int(amount) <= 0:
        raise QPayError("amount must be > 0")

    auth_url = (auth_url or f"{base}/v2/auth/token").strip()
    invoice_url = (invoice_url or f"{base}/v2/invoice").strip()

    # 1) Get access token
    with httpx.Client(timeout=20.0) as client:
        auth_res = client.post(auth_url, auth=(username, password))

    if auth_res.status_code >= 400:
        raise QPayError(f"Auth failed {auth_res.status_code}: {auth_res.text}")

    try:
        auth_payload = auth_res.json()
    except Exception as e:
        raise QPayError(f"Auth JSON parse failed: {e}")

    access_token = str(auth_payload.get("access_token") or "").strip()
    if not access_token:
        # Some implementations return token under different keys.
        access_token = str(auth_payload.get("token") or "").strip()
    if not access_token:
        raise QPayError(f"Auth response missing access_token: {auth_payload}")

    payload: dict[str, Any] = {
        "invoice_code": invoice_code,
        "sender_invoice_no": reference_id,
        "invoice_description": description,
        "amount": int(amount),
    }
    if callback_url:
        payload["callback_url"] = str(callback_url)

    if extra_payload:
        payload.update(extra_payload)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    with httpx.Client(timeout=20.0) as client:
        inv_res = client.post(invoice_url, headers=headers, content=json.dumps(payload))

    if inv_res.status_code >= 400:
        raise QPayError(f"Invoice create failed {inv_res.status_code}: {inv_res.text}")

    try:
        inv_payload = inv_res.json()
    except Exception as e:
        raise QPayError(f"Invoice JSON parse failed: {e}")

    if not isinstance(inv_payload, dict):
        raise QPayError("Invalid invoice response")

    qr_text = inv_payload.get("qr_text")
    if not isinstance(qr_text, str):
        qr_text = None

    qr_image = inv_payload.get("qr_image")
    if not isinstance(qr_image, str):
        qr_image = None

    return QPayInvoice(
        invoice_id=_extract_invoice_id(inv_payload),
        payment_url=_pick_payment_url(inv_payload),
        qr_text=qr_text,
        qr_image=qr_image,
        raw=inv_payload,
    )
