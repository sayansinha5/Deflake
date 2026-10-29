"""Runs the flake subgraph for every flaky test, at most three at a time."""
import asyncio

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.models import Diagnosis, Flake, Patch, Run, utcnow
from app.graph.build import build_flake_graph
from app.graph.checkpointer import mysql_checkpointer
from app.graph.context import GraphContext, current_context
from app.graph.gates import gate
from app.graph.nodes.bisect import bisect_polluter
from app.graph.nodes.common import note_error
from app.graph.nodes.escalate import escalate
from app.graph.nodes.patch import fixable, patch
from app.graph.nodes.score import route, score_confidence
from app.graph.nodes.verify import verify
from app.integrations.tavily import TavilySearch
from app.llm.factory import Llm
from app.services.bisection import SUSPECTED, skipped_record
from app.services.events import append_event

log = structlog.get_logger()

PARALLEL_FLAKES = 3
STEPS = ("classify", "research", "diagnose", "patch")


def _set_step(run: Run, name: str, **fields) -> None:
    steps = dict(run.steps or {})
    current = dict(steps.get(name) or {})
    current.update(fields)
    steps[name] = current
    run.steps = steps


async def _pending(session, settings: Settings, run_id: str) -> list[Flake]:
    flakes = list(await session.scalars(
        select(Flake).where(Flake.run_id == run_id, Flake.state != "broken")
        .order_by(Flake.test_id)
    ))
    pending = []
    for flake in flakes:
        diagnosed = await session.scalar(
            select(Diagnosis.id).where(Diagnosis.flake_id == flake.id, Diagnosis.attempt == 1)
        )
        if diagnosed is None:
            pending.append(flake)
            continue
        if flake.error:
            flake.error = None
            flake.updated_at = utcnow()
        if not fixable(flake.category, False):
            continue
        needs_human = await session.scalar(
            select(Diagnosis.needs_human).where(
                Diagnosis.flake_id == flake.id, Diagnosis.attempt == 1,
            )
        )
        if needs_human or flake.routing:
            continue
        # A proof, a proposal, or an apply failure is finished. Do not ask again.
        settled = await session.scalar(
            select(Patch.id).where(
                Patch.flake_id == flake.id,
                Patch.status.in_(("proposed", "verified", "failed_verify", "failed_apply")),
            )
        )
        if settled is not None:
            continue
        attempts = int(await session.scalar(
            select(func.count()).select_from(Patch).where(Patch.flake_id == flake.id)
        ) or 0)
        if attempts < settings.max_patch_attempts:
            pending.append(flake)
    return pending


async def bisect_flakes(maker, settings: Settings, run_id: str, runner) -> str | None:
    """Bisect flakes that already have a category. A fresh flake is bisected in the graph."""
    ctx = GraphContext(
        settings=settings,
        sessionmaker=maker,
        llm=Llm(settings, session_factory=maker),
        search=None,
        runner=runner,
    )
    token = current_context.set(ctx)
    try:
        async with maker() as session:
            flakes = list(await session.scalars(
                select(Flake).where(Flake.run_id == run_id, Flake.bisection.is_(None))
                .order_by(Flake.test_id)
            ))
            run = await session.get(Run, run_id)
            if run is None:
                return "failed"
            targets: list[tuple[str, str]] = []
            for flake in flakes:
                if flake.state == "broken" or not flake.category:
                    continue
                if flake.category not in SUSPECTED:
                    flake.bisection = skipped_record()
                    flake.updated_at = utcnow()
                    await append_event(session, run, "step.completed", {
                        "step": "bisect", "flake_id": flake.id, "status": "skipped",
                    })
                    continue
                targets.append((flake.id, flake.test_id))
            await session.commit()
        for flake_id, test_id in targets:
            state = await bisect_polluter({
                "run_id": run_id, "flake_id": flake_id, "test_id": test_id,
            })
            reason = state.get("stopped")
            if reason:
                return reason
        return None
    finally:
        current_context.reset(token)


async def _stop_phase(maker, run_id: str, status: str) -> str:
    async with maker() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return "failed"
        ended = utcnow().isoformat()
        for name in STEPS:
            _set_step(run, name, status=status, ended_at=ended)
        await append_event(session, run, "log.line", {
            "level": "info", "message": f"Diagnosis stopped: {status}.",
        })
        await session.commit()
    return status


async def diagnose_flakes(
    maker: async_sessionmaker, settings: Settings, run_id: str, *,
    search=None, checkpointer=None, runner=None,
) -> str | None:
    """Classify, bisect, research, diagnose and patch. Returns a stop status or None."""
    async with maker() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return "failed"
        config = dict(run.config or {})
        config["phase_started_at"] = utcnow().isoformat()
        run.config = config
        await session.commit()

    if runner is not None:
        stop = await bisect_flakes(maker, settings, run_id, runner)
        if stop:
            return await _stop_phase(maker, run_id, stop)

    async with maker() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return "failed"
        reason = await gate(session, settings, run_id)
        pending = await _pending(session, settings, run_id)
        now = utcnow().isoformat()
        if reason:
            status = "cancelled" if reason == "cancelled" else reason
            for name in STEPS:
                _set_step(run, name, status=status, ended_at=now)
            await session.commit()
            return reason
        if pending:
            for name in STEPS:
                _set_step(run, name, status="running", started_at=now)
        await session.commit()

    if pending:
        await _diagnose_pending(
            maker, settings, run_id, pending, search=search, checkpointer=checkpointer,
            runner=runner,
        )
        async with maker() as session:
            reason = await gate(session, settings, run_id)
            if reason:
                return await _stop_phase(maker, run_id, reason)

    if runner is not None:
        stop = await verify_and_route(maker, settings, run_id, runner)
        if stop:
            return await _stop_phase(maker, run_id, stop)
    return None


async def _mark_proof(maker, run_id: str, status: str | None) -> None:
    async with maker() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        ended = utcnow().isoformat()
        for name in ("verify", "route", "escalate"):
            _set_step(run, name, status="done" if status is None else status, ended_at=ended)
        await session.commit()


async def verify_and_route(maker, settings: Settings, run_id: str, runner) -> str | None:
    """Prove proposed patches, route every flake, and submit escalations."""
    ctx = GraphContext(
        settings=settings,
        sessionmaker=maker,
        llm=Llm(settings, session_factory=maker),
        search=None,
        runner=runner,
    )
    token = current_context.set(ctx)
    try:
        async with maker() as session:
            run = await session.get(Run, run_id)
            if run is None:
                return "failed"
            started = utcnow().isoformat()
            for name in ("verify", "route", "escalate"):
                _set_step(run, name, status="running", started_at=started)
            flakes = list(await session.scalars(
                select(Flake).where(Flake.run_id == run_id, Flake.state != "broken")
                .order_by(Flake.test_id)
            ))
            targets = [(flake.id, flake.test_id) for flake in flakes]
            await session.commit()
        for flake_id, test_id in targets:
            state = {"run_id": run_id, "flake_id": flake_id, "test_id": test_id}
            for node in (verify, score_confidence, route, escalate):
                result = await node(state)
                reason = result.get("stopped")
                if reason:
                    await _mark_proof(maker, run_id, reason)
                    return reason
        await _mark_proof(maker, run_id, None)
        return None
    finally:
        current_context.reset(token)


async def _diagnose_pending(
    maker, settings, run_id, pending, *, search, checkpointer, runner,
) -> None:
    ctx = GraphContext(
        settings=settings,
        sessionmaker=maker,
        llm=Llm(settings, session_factory=maker),
        search=search if search is not None else TavilySearch(settings),
        runner=runner,
    )

    async def _one(flake: Flake, graph) -> None:
        token = current_context.set(ctx)
        try:
            async with maker() as session:
                diagnosed = await session.scalar(
                    select(Diagnosis.id).where(
                        Diagnosis.flake_id == flake.id, Diagnosis.attempt == 1,
                    )
                )
            state = {"run_id": run_id, "flake_id": flake.id, "test_id": flake.test_id}
            if diagnosed is not None:
                # A finished checkpoint does not know about the patch node added later.
                await patch(state)
            else:
                await graph.ainvoke(
                    state, config={"configurable": {"thread_id": f"{run_id}:{flake.id}"}},
                )
        except Exception as exc:
            log.exception("flake_graph_failed", flake_id=flake.id)
            await note_error(ctx, run_id, flake.id, exc)
        finally:
            current_context.reset(token)

    async def _fanout(graph) -> None:
        semaphore = asyncio.Semaphore(PARALLEL_FLAKES)

        async def _limited(flake: Flake) -> None:
            async with semaphore:
                await _one(flake, graph)

        await asyncio.gather(*(_limited(flake) for flake in pending))

    if checkpointer is None:
        async with mysql_checkpointer(settings) as saver:
            await _fanout(build_flake_graph(saver))
    else:
        await _fanout(build_flake_graph(checkpointer))

    async with maker() as session:
        reason = await gate(session, settings, run_id)
        run = await session.get(Run, run_id)
        ended = utcnow().isoformat()
        for name in STEPS:
            _set_step(run, name, status="done" if reason is None else reason, ended_at=ended)
        if reason:
            await append_event(session, run, "log.line", {
                "level": "info", "message": f"Diagnosis stopped: {reason}.",
            })
        await session.commit()
