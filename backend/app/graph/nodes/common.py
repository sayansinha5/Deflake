import structlog

from app.db.models import Flake, Run, utcnow
from app.graph.context import GraphContext
from app.security.redact import redact
from app.services.events import append_event

log = structlog.get_logger()


async def note_error(ctx: GraphContext, run_id: str, flake_id: str, exc: Exception) -> None:
    message = redact(str(exc))[:500] or type(exc).__name__
    async with ctx.sessionmaker() as session:
        flake = await session.get(Flake, flake_id)
        run = await session.get(Run, run_id)
        if flake is not None:
            flake.error = message
            flake.updated_at = utcnow()
        if run is not None:
            await append_event(session, run, "flake.updated", {
                "flake_id": flake_id, "state": flake.state if flake else None, "error": message,
            })
        await session.commit()
    log.warning("flake_node_failed", flake_id=flake_id, error=type(exc).__name__)
