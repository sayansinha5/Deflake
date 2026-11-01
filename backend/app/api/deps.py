from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import RevokedSession, User
from app.errors import ApiError
from app.security.auth import (
    COOKIE_NAME,
    SessionClaims,
    SessionExpired,
    SessionInvalid,
    decode_token,
)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


@dataclass
class CurrentSession:
    user: User
    claims: SessionClaims


def _unauthenticated() -> ApiError:
    return ApiError(401, "unauthenticated", "Sign in to continue.")


async def current_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> CurrentSession:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise _unauthenticated()
    try:
        claims = decode_token(settings, token)
    except SessionExpired:
        raise ApiError(
            401, "session_expired", "Your session expired. Sign in to continue."
        ) from None
    except SessionInvalid:
        raise _unauthenticated() from None

    revoked = await db.scalar(select(RevokedSession.jti).where(RevokedSession.jti == claims.jti))
    if revoked:
        raise _unauthenticated()
    user = await db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _unauthenticated()
    if user.sessions_valid_after is not None:
        valid_after = user.sessions_valid_after.replace(tzinfo=UTC)
        if claims.issued_at < valid_after:
            raise _unauthenticated()
    return CurrentSession(user=user, claims=claims)


async def require_owner(session: CurrentSession = Depends(current_session)) -> CurrentSession:
    # Role comes from the database (loaded with the session). Do not also require
    # claims.is_admin — that flag is set at login and goes stale after onboarding
    # promotes a member to owner until the cookie is re-issued.
    if session.user.role != "owner":
        raise ApiError(403, "forbidden", "Only the workspace owner can do this.")
    return session
