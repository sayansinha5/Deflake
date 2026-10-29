from app.db.models import Evidence, Flake, Run, utcnow
from app.graph.context import current_context
from app.graph.gates import gate
from app.graph.nodes.common import note_error
from app.graph.state import FlakeState
from app.graph.text import evidence_text, untrusted
from app.llm.prompts import prompt
from app.llm.schemas import ClassifyOut
from app.llm.usage import BudgetExceeded
from app.services.events import append_event


async def classify(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
    async with ctx.sessionmaker() as session:
        reason = await gate(session, ctx.settings, state["run_id"])
        if reason:
            return {"stopped": reason}
        flake = await session.get(Flake, state["flake_id"])
        if flake is None:
            return {"stopped": "error"}
        if flake.category:
            return {"category": flake.category}
        evidence = await session.get(Evidence, state["flake_id"])
        run = await session.get(Run, state["run_id"])
        await append_event(session, run, "step.started", {
            "step": "classify", "flake_id": flake.id,
        })
        await session.commit()
        body, _ids = evidence_text(
            evidence.failing_samples if evidence else [],
            evidence.passing_samples if evidence else [],
        )
        test_id = flake.test_id
        rate = f"{flake.fail_count}/{flake.run_count}"

    version, system = prompt("classify")
    try:
        parsed = await ctx.llm.structured(
            ClassifyOut,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": (
                    f"Failure rate: {rate}\n"
                    f"Test id:\n{untrusted(test_id)}\n"
                    f"Evidence:\n{untrusted(body)}"
                )},
            ],
            tier="fast", node="classify", temperature=0.0,
            run_id=state["run_id"], flake_id=state["flake_id"], prompt_version=version,
        )
    except BudgetExceeded:
        return {"stopped": "stopped_budget"}
    except Exception as exc:
        await note_error(ctx, state["run_id"], state["flake_id"], exc)
        return {"stopped": "error"}

    async with ctx.sessionmaker() as session:
        flake = await session.get(Flake, state["flake_id"])
        run = await session.get(Run, state["run_id"])
        flake.category = parsed.category
        flake.state = "classified"
        flake.updated_at = utcnow()
        await append_event(session, run, "step.completed", {
            "step": "classify", "flake_id": flake.id, "category": parsed.category,
        })
        await append_event(session, run, "flake.updated", {
            "flake_id": flake.id, "state": flake.state, "category": parsed.category,
        })
        await session.commit()
    return {"category": parsed.category}
