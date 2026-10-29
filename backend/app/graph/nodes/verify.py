"""Rerun a proposed patch until the proof is powered, then check the whole suite."""
import structlog
from sqlalchemy import select

from app.db.models import Flake, Patch, Run, Verification, utcnow
from app.errors import ApiError
from app.graph.context import current_context
from app.graph.gates import gate
from app.graph.nodes.common import note_error
from app.graph.state import FlakeState
from app.services.bisection import failure_count
from app.services.detect import FAIL_OUTCOMES
from app.services.events import append_event
from app.services.stats import plan_verification, upper_bound_zero_failures

log = structlog.get_logger()

BATCH = 40


def _regressions(result: dict) -> list[str]:
    names: list[str] = []
    for iteration in result.get("iterations") or []:
        if (iteration.get("status") or "ok") != "ok":
            names.append("suite did not finish")
            continue
        for row in iteration.get("results") or []:
            if row.get("outcome") in FAIL_OUTCOMES and row.get("test_id") not in names:
                names.append(row["test_id"])
    return names[:50]


async def _allow(ctx, run_id: str) -> str | None:
    async with ctx.sessionmaker() as session:
        return await gate(session, ctx.settings, run_id)


async def _submit(ctx, job: dict) -> dict:
    return await ctx.runner.submit(job)


async def verify(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
    if ctx.runner is None:
        return {}
    run_id, flake_id = state["run_id"], state["flake_id"]
    async with ctx.sessionmaker() as session:
        reason = await gate(session, ctx.settings, run_id)
        if reason:
            return {"stopped": reason}
        flake = await session.get(Flake, flake_id)
        run = await session.get(Run, run_id)
        if flake is None or run is None or flake.state == "broken":
            return {}
        if flake.routing:
            return {}
        proposed = await session.scalar(
            select(Patch).where(Patch.flake_id == flake.id, Patch.status == "proposed")
            .order_by(Patch.attempt.desc())
        )
        if proposed is None:
            return {}
        existing = await session.scalar(
            select(Verification.id).where(Verification.patch_id == proposed.id)
        )
        if existing is not None:
            return {}
        requested = int((run.config or {}).get("verify_reruns") or ctx.settings.verify_reruns)
        reruns, powered = plan_verification(
            flake.ci_low, requested, ctx.settings.verify_reruns_max,
        )
        flake.state = "verifying"
        flake.error = None
        flake.updated_at = utcnow()
        await append_event(session, run, "step.started", {
            "step": "verify", "flake_id": flake.id, "reruns": reruns,
        })
        await session.commit()
        diff = proposed.diff
        patch_id = proposed.id
        victim = flake.test_id
        repo_id = run.repo_id
        timeout_s = ctx.settings.per_test_run_timeout_s
        known = set(await session.scalars(
            select(Flake.test_id).where(Flake.run_id == run_id)
        ))

    log.info("verify_start", flake_id=flake_id, reruns=reruns, powered=powered)

    try:
        done, failures, stop = await _rerun(
            ctx, run_id, flake_id, repo_id, diff, victim, reruns, timeout_s,
        )
    except ApiError as exc:
        status = "failed_apply" if exc.code == "patch_rejected" else "failed_verify"
        await _store(
            ctx, run_id, flake_id, patch_id, status=status, outcome="inconclusive",
            reruns=0, failures=0, ub95=None, power_ok=False, full_suite_passed=None,
            regressions=[],
        )
        return {}
    except Exception as exc:
        await note_error(ctx, run_id, flake_id, exc)
        return {}
    if stop:
        return {"stopped": stop}

    full_passed = None
    regressions: list[str] = []
    if failures == 0:
        try:
            reason = await _allow(ctx, run_id)
            if reason:
                return {"stopped": reason}
            suite = await _submit(ctx, {
                "repo_id": repo_id, "patch": diff, "mode": "suite", "iterations": 1,
                "random_order": False, "timeout_s": timeout_s,
            })
        except ApiError as exc:
            status = "failed_apply" if exc.code == "patch_rejected" else "failed_verify"
            await _store(
                ctx, run_id, flake_id, patch_id, status=status, outcome="inconclusive",
                reruns=done, failures=failures, ub95=None, power_ok=False,
                full_suite_passed=False, regressions=[],
            )
            return {}
        except Exception as exc:
            await note_error(ctx, run_id, flake_id, exc)
            return {}
        failed = _regressions(suite)
        regressions = [name for name in failed if name not in known]
        if victim in failed and victim not in regressions:
            regressions.append(victim)
        full_passed = not regressions and "suite did not finish" not in failed

    if failures > 0 or full_passed is False:
        outcome = "inconclusive"
        patch_status = "failed_verify"
        power_ok = False
        bound = None
    elif not powered:
        outcome = "underpowered"
        patch_status = "proposed"
        power_ok = False
        bound = upper_bound_zero_failures(done)
    else:
        outcome = "verified"
        patch_status = "verified"
        power_ok = True
        bound = upper_bound_zero_failures(done)

    await _store(
        ctx, run_id, flake_id, patch_id, status=patch_status, outcome=outcome,
        reruns=done, failures=failures, ub95=bound, power_ok=power_ok,
        full_suite_passed=full_passed, regressions=regressions,
    )
    log.info(
        "verify_done", flake_id=flake_id, outcome=outcome, reruns=done, failures=failures,
    )
    return {}


async def _rerun(ctx, run_id, flake_id, repo_id, diff, victim, reruns, timeout_s):
    done = 0
    failures = 0
    while done < reruns:
        reason = await _allow(ctx, run_id)
        if reason:
            return done, failures, reason
        batch = min(BATCH, reruns - done)
        result = await _submit(ctx, {
            "repo_id": repo_id, "patch": diff, "mode": "suite", "iterations": batch,
            "random_order": True, "timeout_s": timeout_s,
        })
        got = result.get("iterations") or []
        if not got:
            raise ApiError(502, "runner_error", "The test runner returned no iterations.")
        failures += failure_count(result, victim)
        done += len(got)
        log.info("verify_batch", flake_id=flake_id, done=done, failures=failures)
        if failures:
            break
    return done, failures, None


async def _store(
    ctx, run_id, flake_id, patch_id, *, status, outcome, reruns, failures, ub95,
    power_ok, full_suite_passed, regressions,
) -> None:
    async with ctx.sessionmaker() as session:
        patch = await session.get(Patch, patch_id)
        flake = await session.get(Flake, flake_id)
        run = await session.get(Run, run_id)
        if patch is None or flake is None or run is None:
            return
        already = await session.scalar(
            select(Verification.id).where(Verification.patch_id == patch_id)
        )
        if already is None:
            session.add(Verification(
                patch_id=patch_id, reruns=reruns, failures=failures, ub95=ub95,
                power_ok=power_ok, full_suite_passed=full_suite_passed,
                regressions=regressions, outcome=outcome,
            ))
        if status != "proposed":
            patch.status = status
        if outcome == "verified":
            flake.state = "verified"
        elif outcome == "underpowered":
            flake.state = "underpowered"
        else:
            flake.state = "inconclusive"
        flake.updated_at = utcnow()
        await append_event(session, run, "step.completed", {
            "step": "verify", "flake_id": flake.id, "outcome": outcome,
            "reruns": reruns, "failures": failures, "power_ok": power_ok,
            "full_suite_passed": full_suite_passed,
        })
        await append_event(session, run, "flake.updated", {
            "flake_id": flake.id, "state": flake.state,
        })
        await session.commit()
