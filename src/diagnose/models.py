"""The `diagnoses` table: a durable, complete record of every LLM
consultation -- successful or not. Failures are recorded too, not just
successes: an honest audit trail of "we tried and here's what happened" is
part of what makes this project's AI usage inspectable, not just its wins.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("payments.order_id"), nullable=False
    )
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_bundle: Mapped[dict] = mapped_column(JSONB, nullable=False)

    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    cited_evidence_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    suggested_intervention: Mapped[str | None] = mapped_column(String(32), nullable=True)

    raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
