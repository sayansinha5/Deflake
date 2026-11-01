from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db
from app.schemas.auth import UUID_PATTERN
from app.schemas.workspaces import NotificationListOut, NotificationOut, UnreadCountOut
from app.services import notifications as notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(note) -> NotificationOut:
    return NotificationOut(
        id=note.id,
        type=note.type,
        title=note.title,
        body=note.body,
        link=note.link,
        data=note.data,
        read_at=note.read_at,
        created_at=note.created_at,
    )


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> NotificationListOut:
    items, total, unread = await notification_service.list_notifications(
        db, session.user.id, limit=limit, offset=offset,
    )
    return NotificationListOut(
        items=[_out(n) for n in items],
        total=total,
        unread=unread,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def get_unread_count(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountOut:
    return UnreadCountOut(unread=await notification_service.unread_count(db, session.user.id))


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def read_notification(
    notification_id: str = Path(pattern=UUID_PATTERN),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> NotificationOut:
    note = await notification_service.mark_read(db, session.user.id, notification_id)
    await db.commit()
    return _out(note)


@router.post("/read-all", response_model=UnreadCountOut)
async def read_all(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountOut:
    await notification_service.mark_all_read(db, session.user.id)
    await db.commit()
    return UnreadCountOut(unread=0)
