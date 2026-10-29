"""Run the graph again for one finished scan, without another detection pass.

    docker compose -f backend/docker-compose.yml exec api python scripts/continue_run.py <run-id>
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.engine import build_engine, build_sessionmaker  # noqa: E402
from app.graph.run import diagnose_flakes  # noqa: E402
from app.runner_client import RunnerClient  # noqa: E402


async def main() -> int:
    if len(sys.argv) != 2:
        print("usage: continue_run.py <run-id>")
        return 1
    settings = get_settings()
    engine = build_engine(settings)
    maker = build_sessionmaker(engine)
    reason = await diagnose_flakes(
        maker, settings, sys.argv[1], runner=RunnerClient(settings),
    )
    print(f"phase_status={reason or 'done'}")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
