"""outbox_entries and circuit_breaker_state.

An OutboxEntry is written in the *same transaction* as the Decision it
belongs to (see src/execute/outbox.py) -- the decision and the intent to
act on it either both land or neither does, closing the gap ADR-003 exists
to close. idempotency_key is unique and doubles as the Razorpay
reference_id on every create-payment-link call for this entry, since
Razorpay's Payment Links API has no native idempotency header of its own.

CircuitBreakerState is a single row per external service (just "razorpay"
today) so the breaker's state is shared and durable across dispatcher runs
and restarts, not reset every time the process does.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class OutboxEntry(Base):
    __tablename__ = "outbox_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    intervention: Mapped[str] = mapped_column(String(32), nullable=False)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    razorpay_payment_link_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    razorpay_short_url: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CircuitBreakerState(Base):
    __tablename__ = "circuit_breaker_state"

    service: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="closed")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
