from __future__ import annotations

from pydantic import BaseModel


class QPayWebhookPayload(BaseModel):
    invoice_id: str
    status: str
