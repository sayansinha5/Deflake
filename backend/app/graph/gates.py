"""Cancel, time budget, and model-spend checks shared by every flake node."""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Run, utcnow
from app.llm.usage import BudgetExceeded, assert_budget


async def gate(session: AsyncSession, settings: Settings, run_id: str) -> str | None:
    """None means the node may do work. Otherwise a terminal run status."""
    run = await session.get(Run, run_id)
    if run is None:
        return "failed"
    if run.cancel_requested:
        return "cancelled"
    anchor = (run.config or {}).get("phase_started_at")
    if isinstance(anchor, str):
        started = datetime.fromisoformat(anchor)
    else:
        anchor = (run.config or {}).get("phase_started_at")
    if isinstance(anchor, str):
        started = datetime.fromisoformat(anchor)
    else:
        started = run.started_at or run.created_at
    budget_min = int((run.config or {}).get("time_budget_min") or settings.run_time_budget_min)
    if (utcnow() - started).total_seconds() / 60 >= budget_min:
        return "stopped_time"
    cap = float((run.config or {}).get("cost_budget_usd") or settings.ai_run_budget_usd)
    try:
        await assert_budget(session, run_id, cap)
    except BudgetExceeded:
        return "stopped_budget"
    return None
