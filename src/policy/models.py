"""The `decisions` table: one durable row per policy-engine determination.

This is what Track 3's bar means by "every executed action carries the ID
of the rule that authorised it" -- rule_id and reason are never computed
only in memory and thrown away. proposed_intervention and
authorized_intervention are stored separately so an overridden proposal
(the designed failures from Stage 4) is as visible here as an accepted one.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("payments.order_id"), nullable=False
    )
    payer_contact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    proposed_intervention: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_intervention: Mapped[str] = mapped_column(String(32), nullable=False)
    overridden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(48), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set only for decisions produced by Stage 7's re-diagnosis path; null
    # for every decision made from the deterministic classifier's output.
    diagnosis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diagnoses.id"), nullable=True
    )
