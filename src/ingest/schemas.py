"""Parsing for the subset of the Razorpay webhook envelope this project uses.

Only fields we actually read are declared. Pydantic v2 ignores unknown
fields by default, so the real payload's many other fields (fees, tax,
notes, contact info, ...) pass through untouched -- we're not modelling the
whole entity, just the corner of it Stage 2 needs.
"""

from pydantic import BaseModel


class RazorpayPaymentEntity(BaseModel):
    id: str
    amount: int
    currency: str = "INR"
    status: str
    order_id: str | None = None
    method: str | None = None
    contact: str | None = None
    error_code: str | None = None
    error_reason: str | None = None


class RazorpayWebhookEnvelope(BaseModel):
    event: str
    payload: dict

    def payment_entity(self) -> RazorpayPaymentEntity | None:
        block = self.payload.get("payment", {}).get("entity")
        return RazorpayPaymentEntity.model_validate(block) if block else None
