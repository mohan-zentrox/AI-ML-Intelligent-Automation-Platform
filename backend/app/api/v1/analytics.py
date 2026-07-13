"""
Usage / cost analytics.

Reference: FRD section "Usage & Cost Tracking". Aggregates the UsageLog
table (one row per provider call - embedding or completion) by day and by
user.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import Principal, require_role
from app.core.security import Role
from app.db.session import get_db
from app.models.usage_log import UsageLog
from app.schemas.analytics import UsageByDay, UsageByUser, UsageSummaryResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])

_ANALYTICS_ROLES = (Role.ADMIN, Role.ANALYST)


@router.get("/usage", response_model=UsageSummaryResponse)
def usage_summary(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*_ANALYTICS_ROLES)),
) -> UsageSummaryResponse:
    logs = db.query(UsageLog).all()

    by_day: dict[str, list[UsageLog]] = defaultdict(list)
    by_user: dict[str, list[UsageLog]] = defaultdict(list)
    for log in logs:
        day_key = log.created_at.strftime("%Y-%m-%d")
        by_day[day_key].append(log)
        by_user[log.user_id].append(log)

    day_rows = [
        UsageByDay(
            day=day,
            total_calls=len(rows),
            total_tokens=sum(r.total_tokens for r in rows),
            total_cost_usd=round(sum(r.cost_usd for r in rows), 6),
            avg_latency_ms=round(sum(r.latency_ms for r in rows) / len(rows), 2) if rows else 0.0,
        )
        for day, rows in sorted(by_day.items())
    ]
    user_rows = [
        UsageByUser(
            user_id=user_id,
            total_calls=len(rows),
            total_tokens=sum(r.total_tokens for r in rows),
            total_cost_usd=round(sum(r.cost_usd for r in rows), 6),
        )
        for user_id, rows in sorted(by_user.items())
    ]

    return UsageSummaryResponse(
        by_day=day_rows,
        by_user=user_rows,
        total_cost_usd=round(sum(r.cost_usd for r in logs), 6),
        total_tokens=sum(r.total_tokens for r in logs),
    )
