"""Score a flake from its proof and route it to auto-PR or escalation."""
from sqlalchemy import select

from app.db.models import (
    CalibrationVersion,
    Diagnosis,
    Flake,
    Patch,
    Reference,
    Run,
    Verification,
    utcnow,
)
from app.graph.context import current_context
from app.graph.gates import gate
from app.graph.state import FlakeState
from app.services.confidence import apply_calibration, decide_route, raw_confidence
from app.services.events import append_event


async def _inputs(session, flake: Flake) -> dict:
    diagnosis = await session.scalar(
        select(Diagnosis).where(Diagnosis.flake_id == flake.id, Diagnosis.attempt == 1)
    )
    patches = list(await session.scalars(
        select(Patch).where(Patch.flake_id == flake.id).order_by(Patch.attempt)
    ))
    verification = None
    chosen = None
    for row in reversed(patches):
        found = await session.scalar(
            select(Verification).where(Verification.patch_id == row.id)
        )
        if found is not None:
            verification = found
            chosen = row
            break
    if chosen is None:
        chosen = next(
            (row for row in reversed(patches) if row.status in {"proposed", "verified"}), None,
        )
    matched = await session.scalar(
        select(Reference.id).where(Reference.flake_id == flake.id, Reference.matched.is_(True))
    )
    first = patches[0] if patches else None
    return {
        "diagnosis": diagnosis,
        "patch": chosen,
        "verification": verification,
        "matched": matched is not None,
        "first_clean": bool(
            first is not None and first.status == "proposed" and not first.violations
        ),
        "lines": chosen.lines_changed if chosen is not None else 80,
    }


async def _threshold(session, settings) -> tuple[float, str, list | None]:
    row = await session.scalar(
        select(CalibrationVersion).order_by(CalibrationVersion.created_at.desc())
    )
    if row is not None and row.method == "manual":
        points = list(row.points or []) if row.n_labels >= settings.calibration_min_labels else None
        return float(row.threshold), "manual", points
    if row is None or row.n_labels < settings.calibration_min_labels:
        return settings.confidence_threshold_default, "default", None
    return row.threshold, "calibration", list(row.points or [])


async def score_confidence(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
    run_id, flake_id = state["run_id"], state["flake_id"]
    async with ctx.sessionmaker() as session:
        reason = await gate(session, ctx.settings, run_id)
        if reason:
            return {"stopped": reason}
        flake = await session.get(Flake, flake_id)
        run = await session.get(Run, run_id)
        if flake is None or run is None or flake.state == "broken":
            return {}
        if flake.confidence_raw is not None:
            return {}
        loaded = await _inputs(session, flake)
        diagnosis = loaded["diagnosis"]
        if diagnosis is None:
            return {}
        outcome = loaded["verification"].outcome if loaded["verification"] else None
        raw, parts = raw_confidence(
            agreement_k=diagnosis.agreement_k,
            agreement_n=diagnosis.agreement_n,
            outcome=outcome,
            lines_changed=loaded["lines"],
            first_attempt_clean=loaded["first_clean"],
            self_confidence=diagnosis.self_confidence,
            reference_matched=loaded["matched"],
        )
        _threshold_value, source, points = await _threshold(session, ctx.settings)
        calibrated = raw if points is None else round(apply_calibration(raw, points), 4)
        flake.confidence_raw = raw
        flake.confidence_cal = calibrated
        flake.updated_at = utcnow()
        await append_event(session, run, "step.completed", {
            "step": "score", "flake_id": flake.id, "confidence_raw": raw,
            "confidence_cal": calibrated, "threshold_source": source, "parts": parts,
        })
        await session.commit()
    return {}


async def route(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
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
        if flake.confidence_cal is None:
            return {}
        loaded = await _inputs(session, flake)
        diagnosis = loaded["diagnosis"]
        outcome = loaded["verification"].outcome if loaded["verification"] else None
        threshold, source, _points = await _threshold(session, ctx.settings)
        decision = decide_route(
            outcome=outcome,
            category=flake.category,
            needs_human=bool(diagnosis.needs_human) if diagnosis else False,
            score=flake.confidence_cal,
            threshold=threshold,
        )
        flake.routing = decision
        flake.state = "auto_pr" if decision == "auto_pr" else "escalated"
        flake.updated_at = utcnow()
        await append_event(session, run, "step.completed", {
            "step": "route", "flake_id": flake.id, "routing": decision,
            "threshold": threshold, "threshold_source": source,
        })
        await append_event(session, run, "flake.updated", {
            "flake_id": flake.id, "state": flake.state, "routing": decision,
            "confidence_cal": flake.confidence_cal,
        })
        await session.commit()
    return {}
