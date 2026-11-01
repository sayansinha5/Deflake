"""Loads the checked-in flaky-shop scan when the database has no finished run.

Safe to run on every start. An existing completed or clean run is left unchanged.
This does not start a scan. The fixture is attached to the Owner's personal demo.
"""
import asyncio
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.engine import build_engine, build_sessionmaker  # noqa: E402
from app.db.models import (  # noqa: E402
    Diagnosis,
    Escalation,
    Evidence,
    Flake,
    LlmCall,
    Patch,
    Reference,
    Repo,
    Run,
    RunEvent,
    User,
    Verification,
)
from app.services.allowlist import (  # noqa: E402
    allowlist_file,
    ensure_demo_repos_for_user,
    seed_repos,
)
from app.services.repo_ids import demo_repo_id_for_user  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "seed" / "completed_run.json"
FINISHED = ("completed", "clean")
SKIP = {"run_events": {"id"}}
ORDER = (
    ("run", Run),
    ("flakes", Flake),
    ("evidence", Evidence),
    ("references", Reference),
    ("diagnoses", Diagnosis),
    ("patches", Patch),
    ("verifications", Verification),
    ("escalations", Escalation),
    ("llm_calls", LlmCall),
    ("events", RunEvent),
)


def _coerce(column, value):
    if value is None:
        return None
    name = type(column.type).__name__
    if "DateTime" in name or "DATETIME" in name:
        return datetime.fromisoformat(value)
    if "Numeric" in name:
        return Decimal(value)
    return value


def _objects(model, rows, overrides):
    built = []
    skip = SKIP.get(model.__tablename__, set())
    for raw in rows:
        kwargs = {}
        for column in model.__table__.columns:
            if column.name in skip:
                continue
            if column.name in overrides:
                kwargs[column.name] = overrides[column.name]
                continue
            if column.name not in raw:
                continue
            kwargs[column.name] = _coerce(column, raw[column.name])
        built.append(model(**kwargs))
    return built


async def seed_completed_run() -> str:
    if not FIXTURE.is_file():
        return "No completed-run fixture to load."
    settings = get_settings()
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    engine = build_engine(settings)
    try:
        async with build_sessionmaker(engine)() as db:
            existing = await db.scalar(select(Run.id).where(Run.status.in_(FINISHED)))
            if existing is not None:
                return f"Completed run {existing} already present."
            path = allowlist_file(settings)
            if path.is_file():
                await seed_repos(db, path)
            owner = await db.scalar(select(User).where(User.role == "owner"))
            if owner is None:
                return "No owner account; skipped completed-run fixture."
            await ensure_demo_repos_for_user(db, settings, owner.id)
            demo_id = demo_repo_id_for_user("flaky-shop", owner.id)
            if await db.get(Repo, demo_id) is None:
                return "Owner has no personal demo repo; skipped fixture."
            overrides = {"created_by": owner.id, "repo_id": demo_id}
            for key, model in ORDER:
                rows = payload.get(key) or []
                if key == "run":
                    rows = [rows]
                db.add_all(
                    _objects(model, rows, overrides if key == "run" else {})
                )
                await db.flush()
            await db.commit()
        return f"Loaded completed run {payload['run']['id']} onto {demo_id}."
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(asyncio.run(seed_completed_run()))
