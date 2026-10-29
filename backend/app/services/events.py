from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, RunEvent, utcnow

ACTIVE = {"queued", "running"}
PIPELINE_STEPS = (
    "detect", "classify", "research", "diagnose", "patch", "verify", "route", "escalate",
)


def empty_steps() -> dict:
    return {name: {"status": "waiting"} for name in PIPELINE_STEPS}


async def append_event(
    session: AsyncSession, run: Run, event_type: str, payload: dict | None = None,
) -> RunEvent:
    """Append one event. Locks the run row so parallel flakes cannot reuse a seq."""
    locked = await session.scalar(
        select(Run).where(Run.id == run.id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise RuntimeError("run missing while appending an event")
    locked.last_event_seq += 1
    event = RunEvent(
        run_id=locked.id, seq=locked.last_event_seq, type=event_type, payload=payload or {},
        created_at=utcnow(),
    )
    session.add(event)
    return event


async def events_after(session: AsyncSession, run_id: str, after_seq: int) -> list[RunEvent]:
    stmt = (
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
        .order_by(RunEvent.seq)
    )
    return list(await session.scalars(stmt))
