"""Tables for Stage 2: the current state per order, and a dedup log per delivery.

`Payment` is keyed by order_id (falling back to the payment_id itself when
Razorpay didn't supply one) because "is this customer's payment situation
resolved" is an order-level question -- a retried attempt after a failure is
a different payment_id against the same order, not a status change on the
original one.

`WebhookEvent` is keyed by Razorpay's `x-razorpay-event-id` header and exists
purely to make dedup an O(1) unique-constraint check. It is a separate,
disposable operational table -- the ledger (src/ledger/) is the permanent,
hash-chained record of what actually happened.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class Payment(Base):
    __tablename__ = "payments"

    order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    latest_payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
