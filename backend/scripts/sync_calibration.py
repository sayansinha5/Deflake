"""Read Toloka status and print the calibration view. Does not start a run.

    docker compose -f backend/docker-compose.yml exec api python scripts/sync_calibration.py <run-id>
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.engine import build_engine, build_sessionmaker  # noqa: E402
from app.db.models import AuditBatch, Flake  # noqa: E402
from app.integrations.escalation.base import ProviderError, ProviderUnavailable  # noqa: E402
from app.services.audit import calibration_view, create_batch, sync_batch  # noqa: E402


async def main() -> int:
    if len(sys.argv) != 2:
        print("usage: sync_calibration.py <run-id>")
        return 1
    run_id = sys.argv[1]
    settings = get_settings()
    engine = build_engine(settings)
    maker = build_sessionmaker(engine)
    try:
        async with maker() as session:
            existing = await session.scalar(
                select(AuditBatch.id).order_by(AuditBatch.created_at.desc())
            )
            if existing is None:
                flake_ids = list(await session.scalars(
                    select(Flake.id).where(Flake.run_id == run_id, Flake.state != "broken")
                ))
                batch = await create_batch(session, settings, flake_ids, None)
                await session.commit()
                batch_id = batch.id
                print(
                    f"created batch={batch_id} items={batch.item_count} provider={batch.provider}"
                )
            else:
                batch_id = existing
                print(f"batch={batch_id}")
            try:
                result = await sync_batch(session, settings, batch_id)
                await session.commit()
            except (ProviderUnavailable, ProviderError) as exc:
                result = {"probe": {"reason": type(exc).__name__}}
            probe = result.get("probe") or {}
            print(
                "toloka "
                f"configured={probe.get('configured')} projects={probe.get('projects')} "
                f"runs={probe.get('runs')} reason={probe.get('reason')} "
                f"items_seen={probe.get('items_seen')} completed={probe.get('completed')} "
                f"annotations={probe.get('annotations')}"
            )
            view = await calibration_view(session, settings)
        print(
            "calibration "
            f"source={view['source']} partial={view['partial']} threshold={view['threshold']} "
            f"n_labels={view['n_labels']} points={len(view['points'])} "
            f"reliability={len(view['reliability'])} batches={len(view['batches'])}"
        )
        print("message=" + view["message"])
        email = os.environ.get("OWNER_EMAIL") or ""
        password = os.environ.get("OWNER_PASSWORD") or ""
        if email and password:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30.0) as client:
                signed = await client.post(
                    "/api/auth/session",
                    json={"email": email, "password": password},
                    headers={"X-Requested-With": "deflake"},
                )
                print(f"signin={signed.status_code}")
                if signed.status_code == 204:
                    fetched = await client.get("/api/calibration")
                    body = fetched.json()
                    print(
                        "GET /api/calibration "
                        f"status={fetched.status_code} source={body.get('source')} "
                        f"partial={body.get('partial')} n_labels={body.get('n_labels')} "
                        f"threshold={body.get('threshold')} "
                        f"reliability={len(body.get('reliability') or [])} "
                        f"batches={len(body.get('batches') or [])}"
                    )
                    counts = [
                        bin_["count"] for bin_ in body.get("reliability") or []
                        if isinstance(bin_, dict)
                    ]
                    print("reliability_counts=" + json.dumps(counts))
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
