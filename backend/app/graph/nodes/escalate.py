"""Submit the evidence bundle after a flake is routed to escalate."""
import structlog

from app.db.models import Flake, Run, utcnow
from app.graph.context import current_context
from app.graph.gates import gate
from app.graph.state import FlakeState
from app.services.escalation import submit_flake
from app.services.events import append_event

log = structlog.get_logger()


async def escalate(state: FlakeState) -> dict:
    if state.get("stopped"):
        return {}
    ctx = current_context.get()
    run_id, flake_id = state["run_id"], state["flake_id"]
    try:
        async with ctx.sessionmaker() as session:
            reason = await gate(session, ctx.settings, run_id)
            if reason:
                return {"stopped": reason}
            flake = await session.get(Flake, flake_id)
            run = await session.get(Run, run_id)
            if flake is None or run is None or flake.routing != "escalate":
                return {}
            row, created = await submit_flake(session, ctx.settings, ctx.llm, flake)
            if created:
                await append_event(session, run, "flake.updated", {
                    "flake_id": flake.id,
                    "state": flake.state,
                    "routing": flake.routing,
                    "escalation_id": row.id,
                    "provider": row.provider,
                    "status": row.status,
                })
            await session.commit()
    except Exception as exc:
        log.warning("escalate_failed", error=type(exc).__name__)
        async with ctx.sessionmaker() as session:
            flake = await session.get(Flake, flake_id)
            if flake is not None and not flake.error:
                flake.error = f"Escalation failed ({type(exc).__name__})."
                flake.updated_at = utcnow()
                await session.commit()
    return {}
