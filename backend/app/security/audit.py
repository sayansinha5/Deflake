from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import SecurityLog
from app.security.auth import salted_hash


def record(
    db: AsyncSession,
    settings: Settings,
    action: str,
    outcome: str,
    actor_id: str | None = None,
    ip: str | None = None,
    details: dict | None = None,
) -> None:
    """Adds a security_log row to the session; the caller commits."""
    db.add(SecurityLog(
        action=action,
        outcome=outcome,
        actor_hash=salted_hash(settings, actor_id),
        ip_hash=salted_hash(settings, ip),
        details=details,
    ))
