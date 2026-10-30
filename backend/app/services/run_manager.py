import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Flake, Repo, Run, utcnow
from app.errors import ApiError
from app.runner_client import RunnerClient
from app.security.redact import redact
from app.services.detect import SuiteStartError, detect, store_findings, store_outcomes
from app.services.events import ACTIVE, append_event, empty_steps
from app.services.stats import rarest_detectable_rate

log = structlog.get_logger()

DEFAULT_STEPS = ("detect",)


async def _lock_repo(session: AsyncSession, repo_id: str, user_id: str | None = None) -> Repo:
    stmt = select(Repo).where(Repo.id == repo_id).with_for_update()
    if user_id is not None:
        from app.services.repos_access import visible_repo_filter

        stmt = stmt.where(visible_repo_filter(user_id))
    repo = await session.scalar(stmt)
    if repo is None:
        raise ApiError(404, "repo_not_found", "This repository was not found.")
    return repo


async def active_run_for(session: AsyncSession, repo_id: str) -> Run | None:
    return await session.scalar(
        select(Run).where(Run.repo_id == repo_id, Run.status.in_(ACTIVE))
        .order_by(Run.created_at.desc())
    )


async def active_count(session: AsyncSession) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(Run).where(Run.status.in_(ACTIVE))
    ) or 0)


async def start_run(
    session: AsyncSession, settings: Settings, repo_id: str, user_id: str,
    detect_reruns: int | None, verify_reruns: int | None,
) -> Run:
    detect_n = detect_reruns or settings.detect_reruns
    verify_n = verify_reruns or settings.verify_reruns
    if not 10 <= detect_n <= 100:
        raise ApiError(422, "invalid_request", "Detection reruns must be between 10 and 100.")
    if not 50 <= verify_n <= settings.verify_reruns_max:
        raise ApiError(422, "invalid_request",
                       f"Verification reruns must be between 50 and {settings.verify_reruns_max}.")

    repo = await _lock_repo(session, repo_id, user_id)
    if repo.prepare_status != "ready":
        raise ApiError(
            409,
            "repo_not_ready",
            "This repository is not ready to scan yet. Wait for prepare to finish.",
            {"prepare_status": repo.prepare_status},
        )
    existing = await active_run_for(session, repo_id)
    if existing is not None:
        raise ApiError(409, "run_already_active",
                       "A scan of this repository is already running.",
                       {"run_id": existing.id})
    if await active_count(session) >= settings.max_concurrent_runs:
        raise ApiError(429, "too_many_runs",
                       "Two scans are already running. Wait for one to finish.")

    run = Run(
        repo_id=repo_id, status="queued", created_by=user_id, steps=empty_steps(),
        config={
            "detect_reruns": detect_n, "verify_reruns": verify_n,
            "timeout_s": settings.per_test_run_timeout_s,
            "time_budget_min": settings.run_time_budget_min,
            "cost_budget_usd": settings.ai_run_budget_usd,
        },
    )
    session.add(run)
    await session.flush()
    await append_event(session, run, "run.status", {"status": "queued"})
    await session.commit()
    return run


async def request_cancel(session: AsyncSession, run: Run) -> Run:
    if run.status not in ACTIVE:
        return run
    run.cancel_requested = True
    await append_event(session, run, "log.line", {"level": "info",
                                                  "message": "Cancel requested."})
    await session.commit()
    return run


async def mark_interrupted(session: AsyncSession) -> int:
    runs = list(await session.scalars(select(Run).where(Run.status.in_(ACTIVE))))
    for run in runs:
        run.status = "interrupted"
        run.finished_at = utcnow()
        await append_event(session, run, "run.status", {"status": "interrupted"})
    if runs:
        await session.commit()
    return len(runs)


def _step(run: Run, name: str, **fields) -> None:
    steps = dict(run.steps)
    current = dict(steps.get(name) or {})
    current.update(fields)
    steps[name] = current
    run.steps = steps


async def _cancelled_or_over_budget(
    session: AsyncSession, run_id: str, started: datetime,
) -> str | None:
    run = await session.get(Run, run_id)
    if run is None:
        return "failed"
    if run.cancel_requested:
        return "cancelled"
    budget_min = int((run.config or {}).get("time_budget_min") or 25)
    elapsed = (utcnow() - started.replace(tzinfo=None)).total_seconds() / 60
    if elapsed >= budget_min:
        return "stopped_time"
    return None


async def execute_run(maker: async_sessionmaker[AsyncSession], settings: Settings,
                      client: RunnerClient, run_id: str) -> None:
    started = datetime.now(UTC)
    async with maker() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        run.status = "running"
        run.started_at = utcnow()
        _step(run, "detect", status="running", started_at=run.started_at.isoformat())
        await append_event(session, run, "run.status", {"status": "running"})
        await append_event(session, run, "step.started", {"step": "detect"})
        await session.commit()
        repo_id = run.repo_id
        detect_n = int(run.config["detect_reruns"])
        timeout_s = int(run.config["timeout_s"])

    try:
        summary = None
        async for progress in detect(client, repo_id, detect_n, timeout_s,
                                     settings.runner_batch_size):
            async with maker() as session:
                run = await session.get(Run, run_id)
                stop = await _cancelled_or_over_budget(session, run_id, started)
                if stop:
                    run.status = stop
                    run.finished_at = utcnow()
                    _step(run, "detect", status="cancelled" if stop == "cancelled" else "stopped",
                          ended_at=run.finished_at.isoformat())
                    await append_event(session, run, "run.status", {"status": stop})
                    await append_event(session, run, "run.finished", {"status": stop})
                    await session.commit()
                    return
                if "summary" in progress:
                    summary = progress["summary"]
                else:
                    await store_outcomes(session, run_id, progress["iterations"])
                    progress_text = f"Detect {progress['done']} of {progress['total']}"
                    _step(run, "detect", status="running", progress=progress_text)
                    await append_event(session, run, "step.started", {
                        "step": "detect", "progress": progress_text,
                    })
                    await session.commit()

        async with maker() as session:
            run = await session.get(Run, run_id)
            repo = await session.get(Repo, run.repo_id)
            if summary is None:
                raise RuntimeError("detection produced no summary")
            flakes = await store_findings(session, run_id, summary)
            repo.test_count = summary["test_count"]
            for flake in flakes:
                await append_event(session, run, "flake.detected", {
                    "flake_id": flake.id, "test_id": flake.test_id, "state": flake.state,
                    "fail_count": flake.fail_count, "run_count": flake.run_count,
                    "rate": flake.rate, "ci_low": flake.ci_low, "ci_high": flake.ci_high,
                })
            now = utcnow()
            _step(run, "detect", status="done", ended_at=now.isoformat(),
                  flakes=len(summary["flakes"]), broken=len(summary["broken"]))
            await append_event(session, run, "step.completed", {
                "step": "detect", "flakes": len(summary["flakes"]),
                "broken": len(summary["broken"]),
            })
            flaky_n = len(summary["flakes"])
            broken_n = len(summary["broken"])
            if flaky_n == 0:
                for name in ("classify", "research", "diagnose", "patch"):
                    _step(run, name, status="skipped")
                if broken_n == 0:
                    run.status = "clean"
                    note = (f"a test failing less than about 1 in "
                            f"{round(1 / rarest_detectable_rate(detect_n))} runs may not be "
                            f"detected with {detect_n} reruns")
                    await append_event(session, run, "log.line",
                                       {"level": "info", "message": note})
                else:
                    run.status = "completed"
                run.finished_at = now
                await append_event(session, run, "run.status", {"status": run.status})
                await append_event(session, run, "run.finished", {
                    "status": run.status, "flakes": flaky_n, "broken": broken_n,
                })
                await session.commit()
                return
            await session.commit()

        from app.graph.run import diagnose_flakes

        stop = await diagnose_flakes(
            maker, settings, run_id, runner=RunnerClient(settings),
        )
        await _finish_run(maker, run_id, stop or "completed", flaky_n, broken_n)
    except Exception as exc:
        log.exception("run_failed", run_id=run_id)
        await _fail_run(maker, run_id, exc)


async def _finish_run(maker, run_id: str, status: str, flaky_n: int, broken_n: int) -> None:
    async with maker() as session:
        run = await session.get(Run, run_id)
        run.status = status
        run.finished_at = utcnow()
        await append_event(session, run, "run.status", {"status": status})
        await append_event(session, run, "run.finished", {
            "status": status, "flakes": flaky_n, "broken": broken_n,
        })
        await session.commit()


async def _fail_run(maker, run_id: str, exc: Exception) -> None:
    async with maker() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        detect_done = (run.steps or {}).get("detect", {}).get("status") == "done"
        run.status = "failed"
        run.finished_at = utcnow()
        if isinstance(exc, SuiteStartError):
            run.error_code = "suite_start"
            run.error_message = f"Test suite could not start\n{redact(str(exc))[:400]}"
        else:
            run.error_code = "diagnose_failed" if detect_done else "detect_failed"
            run.error_message = redact(str(exc))[:500]
        if detect_done:
            _step(run, "diagnose", status="failed", ended_at=run.finished_at.isoformat())
        else:
            _step(run, "detect", status="failed", ended_at=run.finished_at.isoformat())
        await append_event(session, run, "run.status", {"status": "failed"})
        await append_event(session, run, "run.finished", {"status": "failed"})
        await session.commit()


async def _resume_diagnosis(maker, settings: Settings, run_id: str) -> None:
    from app.graph.run import diagnose_flakes

    try:
        stop = await diagnose_flakes(
            maker, settings, run_id, runner=RunnerClient(settings),
        )
        async with maker() as session:
            flakes = list(await session.scalars(select(Flake).where(Flake.run_id == run_id)))
        flaky_n = sum(1 for flake in flakes if flake.state != "broken")
        broken_n = sum(1 for flake in flakes if flake.state == "broken")
        await _finish_run(maker, run_id, stop or "completed", flaky_n, broken_n)
    except Exception as exc:
        log.exception("run_failed", run_id=run_id)
        await _fail_run(maker, run_id, exc)


async def resume_run(maker: async_sessionmaker[AsyncSession], settings: Settings,
                     client: RunnerClient, session: AsyncSession, run: Run) -> Run:
    if run.status != "interrupted":
        raise ApiError(409, "run_not_resumable", "Only an interrupted scan can be resumed.")
    detect_done = (run.steps or {}).get("detect", {}).get("status") == "done"
    diagnose_status = (run.steps or {}).get("diagnose", {}).get("status")
    if detect_done and diagnose_status not in {"done", "skipped"}:
        run.status = "running"
        run.finished_at = None
        run.error_code = None
        run.error_message = None
        await append_event(session, run, "run.status", {"status": "running", "resumed": True})
        await session.commit()
        asyncio.create_task(_resume_diagnosis(maker, settings, run.id))
        return run
    if detect_done:
        raise ApiError(
            409, "run_not_resumable",
            "Detection and diagnosis already finished; later steps resume in a later build.",
        )
    from sqlalchemy import delete

    from app.db.models import Evidence, TestOutcome

    flake_ids = select(Flake.id).where(Flake.run_id == run.id)
    await session.execute(delete(Evidence).where(Evidence.flake_id.in_(flake_ids)))
    await session.execute(delete(Flake).where(Flake.run_id == run.id))
    await session.execute(delete(TestOutcome).where(TestOutcome.run_id == run.id))
    run.status = "queued"
    run.finished_at = None
    run.error_code = None
    run.error_message = None
    run.steps = empty_steps()
    await append_event(session, run, "run.status", {"status": "queued", "resumed": True})
    await session.commit()
    asyncio.create_task(execute_run(maker, settings, client, run.id))
    return run
