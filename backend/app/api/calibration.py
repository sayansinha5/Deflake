"""Calibration chart, Toloka sync, CSV import, and the owner threshold."""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep, require_owner
from app.config import Settings
from app.errors import ApiError
from app.integrations.audit.csv_import import MAX_BYTES, CsvError
from app.schemas.auth import UUID_PATTERN, StrictModel
from app.security import audit
from app.security.ratelimit import limiter
from app.services.audit import (
    apply_csv,
    calibration_view,
    create_batch,
    set_threshold,
    sync_batch,
    threshold_ok,
)

router = APIRouter(prefix="/calibration", tags=["calibration"])


class BatchIn(StrictModel):
    flake_ids: list[str] = Field(default_factory=list, max_length=40)


class ThresholdIn(StrictModel):
    threshold: float
    reason: str = Field(min_length=1, max_length=500)


class BatchOut(BaseModel):
    id: str
    provider: str
    external_ref: str | None
    status: str
    item_count: int
    labelled_count: int
    control_accuracy: float | None
    created_at: datetime


class CalibrationOut(BaseModel):
    source: str
    partial: bool
    threshold: float
    suggested_threshold: float | None
    precision_at: float | None
    coverage_at: float | None
    n_labels: int
    min_labels: int
    message: str
    points: list
    reliability: list
    batches: list[BatchOut]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("", response_model=CalibrationOut)
async def get_calibration(
    _user: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    return await calibration_view(db, settings)


@router.post("/batches", status_code=201)
async def post_batch(
    body: BatchIn,
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    for flake_id in body.flake_ids:
        if re.fullmatch(UUID_PATTERN, flake_id) is None:
            raise ApiError(400, "bad_request", "flake_ids must be ids.")
    batch = await create_batch(db, settings, body.flake_ids, session.user.id)
    await db.commit()
    return {"id": batch.id, "provider": batch.provider, "status": batch.status,
            "item_count": batch.item_count}


@router.post("/batches/{batch_id}/sync")
@limiter.limit("30/hour")
async def post_sync(
    request: Request,
    batch_id: str = Path(pattern=UUID_PATTERN),
    _user: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    result = await sync_batch(db, settings, batch_id)
    if not result["found"]:
        raise ApiError(404, "batch_not_found", "Audit batch not found.")
    await db.commit()
    return result


@router.post("/import")
async def post_import(
    request: Request,
    session: CurrentSession = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise ApiError(413, "payload_too_large", "CSV uploads are limited to 1 MB.")
    try:
        batch = await apply_csv(db, settings, raw)
    except CsvError as exc:
        raise ApiError(400, "bad_csv", str(exc)) from exc
    audit.record(
        db, settings, "calibration_import", "success", session.user.id, _client_ip(request),
        {"batch_id": batch.id, "labelled_count": batch.labelled_count},
    )
    await db.commit()
    return {
        "batch_id": batch.id,
        "labelled_count": batch.labelled_count,
        "control_accuracy": batch.control_accuracy,
        "status": batch.status,
    }


@router.put("/threshold", response_model=CalibrationOut)
async def put_threshold(
    body: ThresholdIn,
    request: Request,
    session: CurrentSession = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    if not threshold_ok(body.threshold):
        raise ApiError(400, "bad_request", "Threshold must be from 0.50 to 0.95 in steps of 0.05.")
    await set_threshold(db, settings, body.threshold, body.reason, session.user.id)
    audit.record(
        db, settings, "calibration_threshold", "success", session.user.id, _client_ip(request),
        {"threshold": body.threshold, "reason": body.reason},
    )
    await db.commit()
    return await calibration_view(db, settings)
