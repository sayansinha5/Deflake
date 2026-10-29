"""Loads demo-repos/allowlist.yaml into the repos table. Safe to rerun."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.engine import build_engine, build_sessionmaker
from app.services.allowlist import seed_repos


def _allowlist() -> Path:
    settings = get_settings()
    path = Path(settings.allowlist_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / "demo-repos" / "allowlist.yaml"
    return path


async def main() -> None:
    settings = get_settings()
    path = _allowlist()
    engine = build_engine(settings)
    try:
        async with build_sessionmaker(engine)() as session:
            repos = await seed_repos(session, path)
            await session.commit()
        print(f"Seeded {len(repos)} repositor{'y' if len(repos) == 1 else 'ies'}: "
              + ", ".join(r.id for r in repos))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
