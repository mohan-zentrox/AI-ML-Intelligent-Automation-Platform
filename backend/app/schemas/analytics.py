from __future__ import annotations

from pydantic import BaseModel


class UsageByDay(BaseModel):
    day: str
    total_calls: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float


class UsageByUser(BaseModel):
    user_id: str
    total_calls: int
    total_tokens: int
    total_cost_usd: float


class UsageSummaryResponse(BaseModel):
    by_day: list[UsageByDay]
    by_user: list[UsageByUser]
    total_cost_usd: float
    total_tokens: int
