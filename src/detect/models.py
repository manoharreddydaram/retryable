"""Two tables: `detector_baselines` holds one row per cohort -- its current
EWMA rate, updated in place, mirroring circuit_breaker_state's
one-row-per-key shape. `detector_runs` is the audit trail: one row per
cohort per invocation of the detector, fired or not, so a suppressed alarm
is exactly as visible after the fact as a fired one -- the same principle
Diagnosis applies to failed LLM calls.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class DetectorBaseline(Base):
    __tablename__ = "detector_baselines"

    cohort: Mapped[str] = mapped_column(String(64), primary_key=True)
    ewma_rate: Mapped[float] = mapped_column(Float, nullable=False)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DetectorRun(Base):
    __tablename__ = "detector_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cohort: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_rate: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_rate: Mapped[float] = mapped_column(Float, nullable=False)
    # Null when suppressed before the test could run at all -- there is no
    # probability to report for insufficient_sample/insufficient_history.
    probability_degraded: Mapped[float | None] = mapped_column(Float, nullable=True)
    fired: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # "insufficient_sample" | "insufficient_history" | "not_significant" | None (fired)
    suppressed_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
