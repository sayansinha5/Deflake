from sqlalchemy import select

from app.db.models import Diagnosis, Evidence, Flake, Run, utcnow
from app.graph.agreement import majority
from app.graph.context import current_context
from app.graph.gates import gate
from app.graph.nodes.common import note_error
from app.graph.state import FlakeState
from app.graph.text import evidence_text, untrusted
from app.llm.prompts import prompt
from app.llm.schemas import DiagnoseOut
from app.llm.usage import BudgetExceeded
from app.services.events import append_event


async def diagnose(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
    async with ctx.sessionmaker() as session:
        reason = await gate(session, ctx.settings, state["run_id"])
        if reason:
            return {"stopped": reason}
        existing = await session.scalar(
            select(Diagnosis).where(
                Diagnosis.flake_id == state["flake_id"], Diagnosis.attempt == 1,
            )
        )
        if existing is not None:
            return {"agreement_k": existing.agreement_k, "agreement_n": existing.agreement_n}
        flake = await session.get(Flake, state["flake_id"])
        evidence = await session.get(Evidence, state["flake_id"])
        run = await session.get(Run, state["run_id"])
        if flake is None or run is None:
            return {"stopped": "error"}
        flake.state = "diagnosing"
        flake.updated_at = utcnow()
        await append_event(session, run, "step.started", {
            "step": "diagnose", "flake_id": flake.id,
        })
        await session.commit()
        body, known_ids = evidence_text(
            evidence.failing_samples if evidence else [],
            evidence.passing_samples if evidence else [],
        )
        test_id = flake.test_id
        category = flake.category or "unknown"
        rate = f"{flake.fail_count}/{flake.run_count}"

    version, system = prompt("diagnose")
    samples: list[DiagnoseOut] = []
    sample_count = max(1, ctx.settings.self_consistency_samples)
    for _ in range(sample_count):
        async with ctx.sessionmaker() as session:
            reason = await gate(session, ctx.settings, state["run_id"])
        if reason:
            return {"stopped": reason}
        try:
            parsed = await ctx.llm.structured(
                DiagnoseOut,
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": (
                        f"Classifier category: {category}\n"
                        f"Failure rate: {rate}\n"
                        f"Test id:\n{untrusted(test_id)}\n"
                        f"Evidence:\n{untrusted(body)}"
                    )},
                ],
                tier="reasoning", node="diagnose",
                temperature=ctx.settings.ai_temperature_self_consistency,
                run_id=state["run_id"], flake_id=state["flake_id"], prompt_version=version,
            )
        except BudgetExceeded:
            return {"stopped": "stopped_budget"}
        except Exception as exc:
            await note_error(ctx, state["run_id"], state["flake_id"], exc)
            return {"stopped": "error"}
        samples.append(parsed)

    chosen, agreement_k = majority(samples)
    refs = [ref for ref in chosen.evidence_refs if ref in known_ids]
    async with ctx.sessionmaker() as session:
        already = await session.scalar(
            select(Diagnosis.id).where(
                Diagnosis.flake_id == state["flake_id"], Diagnosis.attempt == 1,
            )
        )
        if already is None:
            session.add(Diagnosis(
                flake_id=state["flake_id"], attempt=1,
                root_cause=chosen.root_cause, mechanism=chosen.mechanism,
                culprit=chosen.culprit, category=chosen.category,
                fix_strategy=chosen.fix_strategy, needs_human=chosen.needs_human,
                self_confidence=chosen.confidence, agreement_k=agreement_k,
                agreement_n=len(samples), evidence_refs=refs,
            ))
        flake = await session.get(Flake, state["flake_id"])
        run = await session.get(Run, state["run_id"])
        flake.state = "diagnosing"
        flake.error = None
        flake.updated_at = utcnow()
        await append_event(session, run, "step.completed", {
            "step": "diagnose", "flake_id": flake.id,
            "agreement_k": agreement_k, "agreement_n": len(samples),
            "needs_human": chosen.needs_human,
        })
        await append_event(session, run, "flake.updated", {
            "flake_id": flake.id, "state": flake.state, "category": flake.category,
            "agreement": f"{agreement_k}/{len(samples)}",
        })
        await session.commit()
    return {"agreement_k": agreement_k, "agreement_n": len(samples)}
