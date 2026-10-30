"""Escalation list and on-demand provider refresh."""
from datetime import datetime

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep
from app.config import Settings
from app.db.models import Escalation, Flake, Repo, Run
from app.errors import ApiError
from app.schemas.auth import UUID_PATTERN
from app.security.ratelimit import limiter
from app.services.escalation import refresh_escalation
from app.services.repos_access import get_visible_flake, visible_repo_filter

router = APIRouter(prefix="/escalations", tags=["escalations"])


class EscalationOut(BaseModel):
    id: str
    flake_id: str
    test_id: str
    provider: str
    external_ref: str | None
    status: str
    reason: str
    bundle: dict
    response: str | None
    attempts: list
    created_at: datetime
    updated_at: datetime


def _out(row: Escalation, test_id: str) -> EscalationOut:
    return EscalationOut(
        id=row.id,
        flake_id=row.flake_id,
        test_id=test_id,
        provider=row.provider,
        external_ref=row.external_ref,
        status=row.status,
        reason=row.reason,
        bundle=row.bundle or {},
        response=row.response,
        attempts=row.attempts or [],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[EscalationOut])
async def list_escalations(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> list[EscalationOut]:
    rows = list(await db.execute(
        select(Escalation, Flake.test_id)
        .join(Flake, Flake.id == Escalation.flake_id)
        .join(Run, Run.id == Flake.run_id)
        .join(Repo, Repo.id == Run.repo_id)
        .where(visible_repo_filter(session.user.id))
        .order_by(Escalation.created_at.desc())
        .limit(100)
    ))
    return [_out(row, test_id) for row, test_id in rows]


@router.post("/{escalation_id}/refresh", response_model=EscalationOut)
@limiter.limit("30/hour")
async def refresh(
    request: Request,
    escalation_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> EscalationOut:
    row = await db.get(Escalation, escalation_id)
    if row is None:
        raise ApiError(404, "escalation_not_found", "Escalation not found.")
    flake = await get_visible_flake(db, row.flake_id, session.user.id)
    try:
        await refresh_escalation(db, settings, row)
        await db.commit()
    except Exception as exc:
        raise ApiError(
            502, "provider_unavailable", f"{row.provider} did not answer ({type(exc).__name__}).",
        ) from exc
    return _out(row, flake.test_id if flake is not None else "")
