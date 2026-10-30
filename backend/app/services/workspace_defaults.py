"""Persisted scan defaults used when a new scan starts."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import WorkspaceDefaults, utcnow
from app.errors import ApiError

DETECT_CHOICES = (20, 30, 50)
VERIFY_CHOICES = (200, 400, 600)
ROW_ID = 1


async def get_defaults(db: AsyncSession, settings: Settings) -> dict[str, int]:
    row = await db.get(WorkspaceDefaults, ROW_ID)
    detect = row.detect_reruns if row is not None else settings.detect_reruns
    verify = row.verify_reruns if row is not None else settings.verify_reruns
    return {"detect_reruns": detect, "verify_reruns": verify}


async def put_defaults(
    db: AsyncSession,
    settings: Settings,
    user_id: str,
    *,
    detect_reruns: int,
    verify_reruns: int,
) -> dict[str, int]:
    if detect_reruns not in DETECT_CHOICES:
        raise ApiError(
            422, "invalid_request",
            f"Detect reruns must be one of: {', '.join(str(n) for n in DETECT_CHOICES)}.",
        )
    if verify_reruns not in VERIFY_CHOICES:
        raise ApiError(
            422, "invalid_request",
            f"Verify reruns must be one of: {', '.join(str(n) for n in VERIFY_CHOICES)}.",
        )
    row = await db.get(WorkspaceDefaults, ROW_ID)
    if row is None:
        row = WorkspaceDefaults(
            id=ROW_ID,
            detect_reruns=detect_reruns,
            verify_reruns=verify_reruns,
            updated_at=utcnow(),
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.detect_reruns = detect_reruns
        row.verify_reruns = verify_reruns
        row.updated_at = utcnow()
        row.updated_by = user_id
    await db.commit()
    await db.refresh(row)
    return {"detect_reruns": row.detect_reruns, "verify_reruns": row.verify_reruns}
