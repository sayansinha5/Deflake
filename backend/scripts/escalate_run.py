"""Submit routed escalations for one finished scan. Does not approve a Tendem task.

    docker compose -f backend/docker-compose.yml exec api python scripts/escalate_run.py <run-id> <test-id>
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.engine import build_engine, build_sessionmaker  # noqa: E402
from app.db.models import Escalation, Flake, Run, utcnow  # noqa: E402
from app.graph.context import GraphContext, current_context  # noqa: E402
from app.graph.nodes.escalate import escalate  # noqa: E402
from app.llm.factory import Llm  # noqa: E402
from app.services.escalation import provider_label, refresh_escalation  # noqa: E402


def _line(row: Escalation, test_id: str, rows: int) -> str:
    source = (row.bundle or {}).get("summary_source")
    failed = [
        f"{item.get('provider')}:{item.get('error')}:{item.get('detail')}"
        for item in (row.attempts or [])
        if not item.get("ok")
    ]
    problems = " ".join(failed) if failed else "none"
    return (
        f"test_id={test_id} escalation_id={row.id} provider={provider_label(row)} "
        f"status={row.status} external_ref={row.external_ref} "
        f"summary_source={source} attempts={len(row.attempts or [])} "
        f"failures={problems} rows={rows}"
    )


async def _one(maker, settings, llm, run_id: str, flake_id: str, test_id: str) -> Escalation:
    ctx = GraphContext(
        settings=settings, sessionmaker=maker, llm=llm, search=None, runner=None,
    )
    token = current_context.set(ctx)
    try:
        await escalate({"run_id": run_id, "flake_id": flake_id, "test_id": test_id})
    finally:
        current_context.reset(token)
    async with maker() as session:
        row = await session.scalar(
            select(Escalation).where(Escalation.idempotency_key == f"{flake_id}:1")
        )
        if row is None:
            raise RuntimeError("escalation row missing")
        return row


async def main() -> int:
    if len(sys.argv) != 3:
        print("usage: escalate_run.py <run-id> <test-id>")
        return 1
    run_id, test_id = sys.argv[1], sys.argv[2]
    settings = get_settings()
    engine = build_engine(settings)
    maker = build_sessionmaker(engine)
    llm = Llm(settings, session_factory=maker)
    try:
        async with maker() as session:
            run = await session.get(Run, run_id)
            if run is None:
                print("run_missing")
                return 1
            config = dict(run.config or {})
            config["phase_started_at"] = utcnow().isoformat()
            run.config = config
            await session.commit()
            flakes = list(await session.scalars(
                select(Flake).where(Flake.run_id == run_id, Flake.test_id == test_id)
            ))
        if len(flakes) != 1:
            print(f"flake_count={len(flakes)}")
            return 1
        flake = flakes[0]
        if flake.routing != "escalate":
            print(f"routing={flake.routing}")
            return 1
        first = await _one(maker, settings, llm, run_id, flake.id, flake.test_id)
        async with maker() as session:
            rows = int(await session.scalar(
                select(func.count()).select_from(Escalation).where(Escalation.flake_id == flake.id)
            ) or 0)
        print("first " + _line(first, flake.test_id, rows))
        async with maker() as session:
            stored = await session.get(Escalation, first.id)
            if stored is not None and stored.external_ref:
                try:
                    await refresh_escalation(session, settings, stored)
                    await session.commit()
                    print(f"poll status={stored.status}")
                except Exception as exc:
                    print(f"poll_error={type(exc).__name__}")
        second = await _one(maker, settings, llm, run_id, flake.id, flake.test_id)
        async with maker() as session:
            rows = int(await session.scalar(
                select(func.count()).select_from(Escalation).where(Escalation.flake_id == flake.id)
            ) or 0)
        print("second " + _line(second, flake.test_id, rows))
        if first.id != second.id or rows != 1:
            print("duplicate_submit")
            return 1
        print("duplicate_ok")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
