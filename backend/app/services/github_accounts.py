"""Persist and revoke connected GitHub OAuth accounts."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import GithubAccount, Repo, new_id, utcnow
from app.errors import ApiError
from app.integrations.github import oauth as gh_oauth
from app.security.token_crypto import decrypt_token, encrypt_token
from app.services.repos_access import PRIVATE_SOURCE

NEEDS_RECONNECT = "needs_reconnect"


async def get_active_account(db: AsyncSession, user_id: str) -> GithubAccount | None:
    return await db.scalar(
        select(GithubAccount).where(
            GithubAccount.user_id == user_id,
            GithubAccount.revoked_at.is_(None),
        )
    )


def connection_public_view(account: GithubAccount | None) -> dict:
    if account is None:
        return {"connected": False}
    return {
        "connected": True,
        "login": account.login,
        "avatar_url": account.avatar_url,
        "scopes": account.scopes,
        "connected_at": account.connected_at.isoformat() + "Z",
    }


async def upsert_connection(
    db: AsyncSession,
    settings: Settings,
    *,
    user_id: str,
    github_user_id: int,
    login: str,
    avatar_url: str | None,
    scopes: str,
    access_token: str,
) -> GithubAccount:
    encrypted = encrypt_token(settings, access_token)
    existing = await db.scalar(
        select(GithubAccount).where(GithubAccount.user_id == user_id)
    )
    if existing is None:
        # Another Deflake user may already own this GitHub user id.
        clash = await db.scalar(
            select(GithubAccount).where(GithubAccount.github_user_id == github_user_id)
        )
        if clash is not None and clash.user_id != user_id:
            raise ApiError(
                409,
                "github_account_in_use",
                "That GitHub account is already connected to another Deflake user.",
            )
        account = GithubAccount(
            id=new_id(),
            user_id=user_id,
            github_user_id=github_user_id,
            login=login,
            avatar_url=avatar_url,
            scopes=scopes,
            access_token_encrypted=encrypted,
            connected_at=utcnow(),
            revoked_at=None,
        )
        db.add(account)
    else:
        clash = await db.scalar(
            select(GithubAccount).where(
                GithubAccount.github_user_id == github_user_id,
                GithubAccount.user_id != user_id,
            )
        )
        if clash is not None:
            raise ApiError(
                409,
                "github_account_in_use",
                "That GitHub account is already connected to another Deflake user.",
            )
        existing.github_user_id = github_user_id
        existing.login = login
        existing.avatar_url = avatar_url
        existing.scopes = scopes
        existing.access_token_encrypted = encrypted
        existing.connected_at = utcnow()
        existing.revoked_at = None
        account = existing
    await db.commit()
    await db.refresh(account)
    return account


async def disconnect(
    db: AsyncSession,
    settings: Settings,
    user_id: str,
) -> None:
    account = await get_active_account(db, user_id)
    if account is None:
        return
    token = None
    try:
        token = decrypt_token(settings, account.access_token_encrypted)
    except ApiError:
        token = None
    if token:
        await gh_oauth.revoke_token(settings, token)
        token = None

    await db.execute(
        update(Repo)
        .where(
            Repo.github_account_id == account.id,
            Repo.source == PRIVATE_SOURCE,
        )
        .values(
            prepare_status=NEEDS_RECONNECT,
            github_account_id=None,
            updated_at=utcnow(),
        )
    )
    await db.delete(account)
    await db.commit()


async def access_token_for_user(
    db: AsyncSession, settings: Settings, user_id: str,
) -> str | None:
    account = await get_active_account(db, user_id)
    if account is None:
        return None
    return decrypt_token(settings, account.access_token_encrypted)


async def mark_disconnected_on_unauthorized(
    db: AsyncSession, user_id: str,
) -> None:
    account = await get_active_account(db, user_id)
    if account is None:
        return
    await db.execute(
        update(Repo)
        .where(
            Repo.github_account_id == account.id,
            Repo.source == PRIVATE_SOURCE,
        )
        .values(
            prepare_status=NEEDS_RECONNECT,
            github_account_id=None,
            updated_at=utcnow(),
        )
    )
    await db.delete(account)
    await db.commit()
