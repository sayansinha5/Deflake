"""Print category, reference count and diagnosis for each flake in a run.

    docker compose -f backend/docker-compose.yml exec api python scripts/show_diagnoses.py
    docker compose -f backend/docker-compose.yml exec api python scripts/show_diagnoses.py <run-id>
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.config import get_settings
from app.db.engine import build_engine, build_sessionmaker
from app.db.models import Diagnosis, Flake, Patch, Reference, Run, Verification


async def main() -> int:
    settings = get_settings()
    engine = build_engine(settings)
    maker = build_sessionmaker(engine)
    async with maker() as session:
        if len(sys.argv) > 1:
            run = await session.get(Run, sys.argv[1])
        else:
            run = await session.scalar(select(Run).order_by(Run.created_at.desc()))
        if run is None:
            print("no run")
            await engine.dispose()
            return 1
        print(f"run_id={run.id} status={run.status}")
        flakes = list(await session.scalars(
            select(Flake).where(Flake.run_id == run.id).order_by(Flake.test_id)
        ))
        for flake in flakes:
            refs = int(await session.scalar(
                select(func.count()).select_from(Reference).where(Reference.flake_id == flake.id)
            ) or 0)
            matched = int(await session.scalar(
                select(func.count()).select_from(Reference).where(
                    Reference.flake_id == flake.id, Reference.matched.is_(True),
                )
            ) or 0)
            diagnosis = await session.scalar(
                select(Diagnosis).where(Diagnosis.flake_id == flake.id, Diagnosis.attempt == 1)
            )
            info = flake.bisection or {}
            names = ", ".join(flake.polluters or []) or "-"
            detail = f" ({info['detail']})" if info.get("detail") else ""
            bisect_line = (
                f"    bisect={info.get('status', '-')} calls={info.get('calls', 0)} "
                f"polluters={names}{detail}"
            )
            if diagnosis is None:
                print(f"  {flake.state:<12} refs={refs}  {flake.test_id}")
                print(bisect_line)
                continue
            cause = " ".join(diagnosis.root_cause.split())[:140]
            print(
                f"  {flake.category or '-':<16} refs={refs} matched={matched}  "
                f"agree={diagnosis.agreement_k}/{diagnosis.agreement_n}  {flake.test_id}"
            )
            print(f"    {cause}")
            patches = list(await session.scalars(
                select(Patch).where(Patch.flake_id == flake.id).order_by(Patch.attempt)
            ))
            for row in patches:
                rules = ",".join(
                    item.get("rule", "") for item in (row.violations or [])
                ) or "-"
                print(f"    patch attempt={row.attempt} status={row.status} rules={rules}")
            print(bisect_line)
            verification = await session.scalar(
                select(Verification).join(Patch, Verification.patch_id == Patch.id)
                .where(Patch.flake_id == flake.id)
                .order_by(Verification.created_at.desc())
            )
            if verification is None:
                print(
                    f"    verify=- route={flake.routing or '-'} "
                    f"raw={flake.confidence_raw} cal={flake.confidence_cal}"
                )
            else:
                suite = verification.full_suite_passed
                print(
                    f"    verify={verification.outcome} reruns={verification.reruns} "
                    f"failures={verification.failures} power={verification.power_ok} "
                    f"suite={suite} route={flake.routing or '-'} "
                    f"raw={flake.confidence_raw} cal={flake.confidence_cal}"
                )
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
