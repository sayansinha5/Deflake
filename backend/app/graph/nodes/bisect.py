"""Find the earlier tests that make a victim fail, using explicit runner order."""
import structlog
from sqlalchemy import select

from app.db.models import Evidence, Flake, Run, TestOutcome, utcnow
from app.graph.context import current_context
from app.graph.gates import gate
from app.graph.nodes.common import note_error
from app.graph.state import FlakeState
from app.security.redact import redact
from app.services.bisection import (
    GATE_STOPS,
    MAX_CALLS,
    NOT_ISOLATED,
    REPEATS,
    SUSPECTED,
    RunnerFailed,
    bisect,
    failure_count,
    skipped_record,
)
from app.services.events import append_event

log = structlog.get_logger()


def _hash_seed(value) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= number < 2**32:
        return number
    return None


def _before(order: list[str], victim: str) -> list[str] | None:
    if victim not in order:
        return None
    seen: set[str] = set()
    prefix = []
    for test_id in order[: order.index(victim)]:
        if test_id == victim or test_id in seen:
            continue
        seen.add(test_id)
        prefix.append(test_id)
    return prefix


async def _candidates(session, run_id: str, flake_id: str, victim: str):
    """Full prefixes from detect outcomes. The evidence window is only a fallback."""
    evidence = await session.get(Evidence, flake_id)
    samples = list((evidence.failing_samples if evidence else None) or [])
    found = []
    seen: set[tuple] = set()
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        prefix = None
        hash_seed = _hash_seed(sample.get("hash_seed"))
        iteration = sample.get("iteration")
        if iteration is not None:
            rows = list(await session.scalars(
                select(TestOutcome).where(
                    TestOutcome.run_id == run_id,
                    TestOutcome.phase == "detect",
                    TestOutcome.iteration == int(iteration),
                ).order_by(TestOutcome.position)
            ))
            prefix = _before([row.test_id for row in rows], victim)
            if hash_seed is None and rows:
                hash_seed = _hash_seed(rows[0].hash_seed)
        if prefix is None:
            prefix = _before(list(sample.get("order_window") or []), victim)
        if not prefix:
            continue
        key = (tuple(prefix), hash_seed)
        if key in seen:
            continue
        seen.add(key)
        found.append((prefix, hash_seed))
    found.sort(key=lambda item: len(item[0]))
    return found


def _absorb(combined: dict, result: dict) -> None:
    for step in result["steps"]:
        item = dict(step)
        item["step"] = len(combined["steps"]) + 1
        combined["steps"].append(item)
    combined["calls"] += result["calls"]


async def _search(ctx, run_id: str, flake_id: str, victim: str, repo_id: str, candidates) -> dict:
    combined = {
        "status": NOT_ISOLATED,
        "polluters": [],
        "calls": 0,
        "steps": [],
        "detail": "empty_prefix",
    }

    async def allow() -> str | None:
        async with ctx.sessionmaker() as session:
            return await gate(session, ctx.settings, run_id)

    for prefix, hash_seed in candidates:
        remaining = MAX_CALLS - combined["calls"]
        if remaining <= 0:
            combined["detail"] = "call_budget"
            break

        async def probe(order: list[str], _seed=hash_seed) -> int:
            job = {
                "repo_id": repo_id,
                "mode": "tests",
                "iterations": REPEATS,
                "random_order": False,
                "order": order,
                "timeout_s": ctx.settings.per_test_run_timeout_s,
            }
            if _seed is not None:
                job["hash_seeds"] = [_seed] * REPEATS
            result = await ctx.runner.submit(job)
            failures = failure_count(result, victim)
            log.info(
                "bisect_probe", flake_id=flake_id, tests=len(order), failures=failures,
            )
            return failures

        result = await bisect(victim, prefix, probe, budget=remaining, allow=allow)
        _absorb(combined, result)
        if hash_seed is not None:
            combined["hash_seed"] = hash_seed
        if result["status"] in GATE_STOPS:
            combined["status"] = result["status"]
            combined["polluters"] = []
            combined.pop("detail", None)
            break
        if result["status"] != NOT_ISOLATED:
            combined["status"] = result["status"]
            combined["polluters"] = list(result["polluters"])
            combined.pop("detail", None)
            break
        combined["detail"] = result.get("detail") or "unstable"
        if combined["detail"] == "call_budget":
            break
    return combined


async def _save(ctx, run_id: str, flake_id: str, record: dict) -> None:
    async with ctx.sessionmaker() as session:
        flake = await session.get(Flake, flake_id)
        run = await session.get(Run, run_id)
        if flake is None or run is None:
            return
        flake.bisection = record
        flake.polluters = list(record["polluters"]) if record["status"] == "isolated" else None
        flake.updated_at = utcnow()
        await append_event(session, run, "step.completed", {
            "step": "bisect",
            "flake_id": flake.id,
            "status": record["status"],
            "polluters": list(flake.polluters or []),
        })
        await append_event(session, run, "flake.updated", {
            "flake_id": flake.id,
            "state": flake.state,
            "polluters": list(flake.polluters or []),
        })
        await session.commit()


def _error_record(exc: Exception) -> dict:
    steps = exc.steps if isinstance(exc, RunnerFailed) else []
    calls = exc.calls if isinstance(exc, RunnerFailed) else 0
    cause = exc.exc if isinstance(exc, RunnerFailed) else exc
    message = redact(str(cause))[:300] or type(cause).__name__
    return {
        "status": "error",
        "polluters": [],
        "calls": calls,
        "steps": steps,
        "detail": message,
    }


async def bisect_polluter(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
    if ctx.runner is None:
        return {}
    run_id, flake_id = state["run_id"], state["flake_id"]
    async with ctx.sessionmaker() as session:
        flake = await session.get(Flake, flake_id)
        run = await session.get(Run, run_id)
        if flake is None or run is None:
            return {"stopped": "error"}
        if flake.bisection is not None:
            return {}
        if not flake.category:
            return {}
        if flake.category not in SUSPECTED:
            await session.commit()
            skip = True
            candidates = []
            repo_id = ""
            victim = flake.test_id
        else:
            skip = False
            victim = flake.test_id
            repo_id = run.repo_id
            candidates = await _candidates(session, run_id, flake_id, victim)
            await append_event(session, run, "step.started", {
                "step": "bisect", "flake_id": flake.id,
            })
            await session.commit()
    if skip:
        await _save(ctx, run_id, flake_id, skipped_record())
        return {}
    try:
        record = await _search(ctx, run_id, flake_id, victim, repo_id, candidates)
    except Exception as exc:
        await _save(ctx, run_id, flake_id, _error_record(exc))
        await note_error(ctx, run_id, flake_id, exc.exc if isinstance(exc, RunnerFailed) else exc)
        return {}
    await _save(ctx, run_id, flake_id, record)
    log.info(
        "bisect_done", flake_id=flake_id, status=record["status"],
        calls=record["calls"], polluters=len(record["polluters"]),
    )
    if record["status"] in GATE_STOPS:
        return {"stopped": record["status"]}
    return {}
