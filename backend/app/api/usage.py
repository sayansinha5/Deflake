"""Token, latency and cost totals from stored model calls. No prices are invented."""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db
from app.db.models import LlmCall, Repo, Run
from app.services.repos_access import visible_repo_filter

router = APIRouter(prefix="/usage", tags=["usage"])


def _percentile(values: list[int], percent: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((percent / 100) * (len(ordered) - 1))
    return ordered[max(0, min(index, len(ordered) - 1))]


def _when(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


@router.get("")
async def get_usage(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    start: str | None = Query(default=None, alias="from"),
    end: str | None = Query(default=None, alias="to"),
) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    window_start = _when(start, now - timedelta(days=7))
    window_end = _when(end, now)
    calls = list(await db.scalars(
        select(LlmCall).where(
            LlmCall.created_at >= window_start,
            LlmCall.created_at <= window_end,
        )
    ))
    tiers: dict[str, dict] = {}
    by_run: dict[str, dict] = {}
    for call in calls:
        bucket = tiers.setdefault(call.tier, {
            "tier": call.tier, "model": call.model, "calls": 0,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latencies": [],
        })
        bucket["calls"] += 1
        bucket["input_tokens"] += call.input_tokens
        bucket["output_tokens"] += call.output_tokens
        bucket["cost_usd"] += float(call.cost_usd or 0)
        bucket["latencies"].append(call.latency_ms)
        if call.model:
            bucket["model"] = call.model
        if call.run_id:
            run_bucket = by_run.setdefault(call.run_id, {
                "run_id": call.run_id, "calls": 0, "input_tokens": 0,
                "output_tokens": 0, "cost_usd": 0.0,
            })
            run_bucket["calls"] += 1
            run_bucket["input_tokens"] += call.input_tokens
            run_bucket["output_tokens"] += call.output_tokens
            run_bucket["cost_usd"] += float(call.cost_usd or 0)
    visible_run_ids: set[str] = set()
    repos: dict[str, str] = {}
    if by_run:
        rows = list(await db.scalars(
            select(Run)
            .join(Repo, Repo.id == Run.repo_id)
            .where(Run.id.in_(list(by_run)))
            .where(visible_repo_filter(session.user.id))
        ))
        visible_run_ids = {row.id for row in rows}
        repos = {row.id: row.repo_id for row in rows}
    return {
        "from": window_start.isoformat() + "Z",
        "to": window_end.isoformat() + "Z",
        "tiers": [
            {
                "tier": row["tier"],
                "model": row["model"],
                "calls": row["calls"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "p50_ms": _percentile(row["latencies"], 50),
                "p95_ms": _percentile(row["latencies"], 95),
                "cost_usd": round(row["cost_usd"], 6),
            }
            for row in tiers.values()
        ],
        "runs": [
            {**row, "repo_id": repos.get(row["run_id"]), "cost_usd": round(row["cost_usd"], 6)}
            for row in sorted(by_run.values(), key=lambda item: item["cost_usd"], reverse=True)
            if row["run_id"] in visible_run_ids
        ],
    }
