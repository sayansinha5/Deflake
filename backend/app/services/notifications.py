"""In-app notifications (poll via API; no broker)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notification, utcnow
from app.errors import ApiError


async def list_notifications(
    db: AsyncSession,
    user_id: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Notification], int, int]:
    total = await db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user_id)
    ) or 0
    unread = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    ) or 0
    rows = (
        await db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return list(rows), int(total), int(unread)


async def unread_count(db: AsyncSession, user_id: str) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(count or 0)


async def mark_read(db: AsyncSession, user_id: str, notification_id: str) -> Notification:
    note = await db.get(Notification, notification_id)
    if note is None or note.user_id != user_id:
        raise ApiError(404, "notification_not_found", "Notification not found.")
    if note.read_at is None:
        note.read_at = utcnow()
        await db.flush()
    return note


async def mark_all_read(db: AsyncSession, user_id: str) -> int:
    rows = (
        await db.scalars(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
        )
    ).all()
    now = utcnow()
    for note in rows:
        note.read_at = now
    await db.flush()
    return len(rows)
