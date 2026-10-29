import asyncio
import json
from datetime import UTC

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep
from app.config import Settings
from app.db.models import Flake, Run
from app.errors import ApiError
from app.schemas.auth import UUID_PATTERN
from app.schemas.runs import REPO_ID, CursorPage, FlakeOut, RunStarted, RunSummary, StartRunIn
from app.security.ratelimit import limiter
from app.services import run_manager
from app.services.events import events_after

router = APIRouter(tags=["runs"])
HEARTBEAT_S = 15


def _summary(run: Run, flake_count: int = 0, broken_count: int = 0) -> RunSummary:
    return RunSummary(
        id=run.id, repo_id=run.repo_id, status=run.status, config=run.config, steps=run.steps,
        created_at=run.created_at, started_at=run.started_at, finished_at=run.finished_at,
        error_code=run.error_code, error_message=run.error_message,
        cost_usd=float(run.cost_usd or 0),
        flake_count=flake_count, broken_count=broken_count,
    )


async def _get_run(db: AsyncSession, run_id: str) -> Run:
    run = await db.get(Run, run_id)
    if run is None:
        raise ApiError(404, "run_not_found", "Run not found.")
    return run


@router.post("/repos/{repo_id}/runs", status_code=202, response_model=RunStarted)
@limiter.limit("10/hour")
async def start_scan(
    request: Request,
    body: StartRunIn,
    repo_id: str = Path(pattern=REPO_ID),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> RunStarted:
    run = await run_manager.start_run(
        db, settings, repo_id, session.user.id, body.detect_reruns, body.verify_reruns,
    )
    asyncio.create_task(run_manager.execute_run(
        request.app.state.sessionmaker, settings, request.app.state.runner, run.id,
    ))
    return RunStarted(run_id=run.id)


@router.get("/runs", response_model=CursorPage)
async def list_runs(
    _user: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = None,
    repo_id: str | None = Query(default=None, pattern=REPO_ID),
) -> CursorPage:
    stmt = select(Run).order_by(Run.created_at.desc(), Run.id.desc())
    if repo_id:
        stmt = stmt.where(Run.repo_id == repo_id)
    if cursor:
        current = await db.get(Run, cursor)
        if current is not None:
            stmt = stmt.where(
                (Run.created_at < current.created_at)
                | ((Run.created_at == current.created_at) & (Run.id < current.id))
            )
    runs = list(await db.scalars(stmt.limit(limit + 1)))
    page, next_cursor = (runs[:limit], runs[limit].id if len(runs) > limit else None)
    counts: dict[str, dict[str, int]] = {}
    if page:
        rows = await db.execute(
            select(Flake.run_id, Flake.state, func.count())
            .where(Flake.run_id.in_([r.id for r in page]))
            .group_by(Flake.run_id, Flake.state)
        )
        for run_id, state, n in rows:
            bucket = counts.setdefault(run_id, {"flaky": 0, "broken": 0})
            bucket["broken" if state == "broken" else "flaky"] += n
    return CursorPage(
        items=[
            _summary(r, flake_count=(counts.get(r.id) or {}).get("flaky", 0),
                     broken_count=(counts.get(r.id) or {}).get("broken", 0))
            for r in page
        ],
        next_cursor=next_cursor,
    )


@router.get("/runs/{run_id}", response_model=RunSummary)
async def get_run(
    run_id: str = Path(pattern=UUID_PATTERN),
    _user: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> RunSummary:
    run = await _get_run(db, run_id)
    rows = await db.execute(
        select(Flake.state, func.count()).where(Flake.run_id == run.id).group_by(Flake.state)
    )
    counts = {"flaky": 0, "broken": 0}
    for state, n in rows:
        counts["broken" if state == "broken" else "flaky"] += n
    return _summary(run, flake_count=counts["flaky"], broken_count=counts["broken"])


@router.get("/runs/{run_id}/flakes", response_model=list[FlakeOut])
async def list_flakes(
    run_id: str = Path(pattern=UUID_PATTERN),
    _user: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> list[FlakeOut]:
    await _get_run(db, run_id)
    flakes = list(await db.scalars(
        select(Flake).where(Flake.run_id == run_id).order_by(Flake.rate.desc(), Flake.test_id)
    ))
    return [FlakeOut.model_validate(f, from_attributes=True) for f in flakes]


@router.post("/runs/{run_id}/cancel", status_code=202, response_model=RunSummary)
async def cancel_run(
    run_id: str = Path(pattern=UUID_PATTERN),
    _user: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> RunSummary:
    run = await run_manager.request_cancel(db, await _get_run(db, run_id))
    return _summary(run)


@router.post("/runs/{run_id}/resume", status_code=202, response_model=RunStarted)
async def resume_run(
    request: Request,
    run_id: str = Path(pattern=UUID_PATTERN),
    _user: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> RunStarted:
    run = await _get_run(db, run_id)
    run = await run_manager.resume_run(
        request.app.state.sessionmaker, settings, request.app.state.runner, db, run,
    )
    return RunStarted(run_id=run.id)


@router.get("/runs/{run_id}/events")
async def stream_events(
    request: Request,
    run_id: str = Path(pattern=UUID_PATTERN),
    _user: CurrentSession = Depends(current_session),
):
    async with request.app.state.sessionmaker() as session:
        await _get_run(session, run_id)
    try:
        after = int(request.headers.get("Last-Event-ID") or 0)
    except ValueError:
        after = 0

    async def generate():
        seq = after
        while True:
            if await request.is_disconnected():
                break
            async with request.app.state.sessionmaker() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    break
                batch = await events_after(session, run_id, seq)
                terminal = run.status not in {"queued", "running"} and not batch
            for event in batch:
                seq = event.seq
                created = event.created_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
                yield {
                    "id": str(event.seq),
                    "event": event.type,
                    "data": json.dumps({"seq": event.seq, "created_at": created, **event.payload}),
                }
            if terminal:
                break
            yield {"comment": "keepalive"}
            await asyncio.sleep(1 if batch else HEARTBEAT_S)

    return EventSourceResponse(generate(), ping=HEARTBEAT_S)
