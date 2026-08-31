"""Turns the payments table into the (observed_count, total_count) pairs
significance.py actually tests. Two cohort shapes, both expressible as a
plain binomial count:

- "overall": failures / (failures + captures) across every payment in the
  window -- the system-health safety net. A spike here means something is
  wrong that no single payment's category can explain on its own.
- "category_share:{category}": this category's failures / all failures in
  the window -- is one failure reason suddenly overrepresented, e.g. an
  infra_outage share climbing from a baseline few percent to half of
  everything failing. This is deliberately a share of failures, not a rate
  against successes: category is only ever set on a failed payment (Stage
  3), so there is no "successful infra_outage" to divide by.

Both cohorts share the same total_count gate downstream in service.py, and
for category_share specifically that total is the same number (total
failures in the window) for every category -- too few failures overall
correctly suppresses every category's share test together, not just some.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.classify.taxonomy import FailureCategory
from src.ingest.models import Payment


@dataclass(frozen=True)
class CohortStats:
    cohort: str
    observed_count: int
    total_count: int


def _in_window(window_start: datetime, window_end: datetime):
    return (Payment.updated_at >= window_start, Payment.updated_at <= window_end)


def overall_stats(session: Session, window_start: datetime, window_end: datetime) -> CohortStats:
    rows = session.execute(
        select(Payment.status, func.count())
        .where(*_in_window(window_start, window_end))
        .group_by(Payment.status)
    ).all()
    counts = dict(rows)
    failed = counts.get("failed", 0)
    captured = counts.get("captured", 0)
    return CohortStats(cohort="overall", observed_count=failed, total_count=failed + captured)


def category_share_stats(
    session: Session, window_start: datetime, window_end: datetime
) -> list[CohortStats]:
    rows = session.execute(
        select(Payment.category, func.count())
        .where(Payment.status == "failed", *_in_window(window_start, window_end))
        .group_by(Payment.category)
    ).all()
    counts_by_category = dict(rows)
    total_failures = sum(counts_by_category.values())

    return [
        CohortStats(
            cohort=f"category_share:{category.value}",
            observed_count=counts_by_category.get(category.value, 0),
            total_count=total_failures,
        )
        for category in FailureCategory
    ]
