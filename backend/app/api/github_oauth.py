"""GitHub OAuth connect / disconnect and connected-repo listing."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep
from app.config import Settings
from app.db.models import RevokedSession, User
from app.errors import ApiError
from app.integrations.github import oauth as gh_oauth
from app.integrations.github.user_repos import list_accessible_repos
from app.security.ratelimit import limiter
from app.services import github_accounts

log = structlog.get_logger()
router = APIRouter(prefix="/github", tags=["github"])


def _require_oauth(settings: Settings) -> None:
    if not settings.github_oauth_enabled:
        raise ApiError(403, "oauth_disabled", "GitHub OAuth is turned off.")


@router.get("/connection")
async def get_connection(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    account = await github_accounts.get_active_account(db, session.user.id)
    view = github_accounts.connection_public_view(account)
    view["oauth_enabled"] = settings.github_oauth_enabled
    return view


@router.get("/oauth/start")
@limiter.limit("10/hour")
async def oauth_start(
    request: Request,
    session: CurrentSession = Depends(current_session),
    settings: Settings = Depends(get_settings_dep),
) -> RedirectResponse:
    _require_oauth(settings)
    state, challenge = gh_oauth.create_oauth_state(session.user.id, session.claims.jti)
    url = gh_oauth.authorize_url(settings, state, challenge)
    return RedirectResponse(url=url, status_code=302)


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> RedirectResponse:
    """Browser returns here from GitHub. No session cookie required; state is the guard."""
    _require_oauth(settings)
    params = request.query_params
    if params.get("error"):
        return RedirectResponse(
            gh_oauth.success_redirect(settings, "denied"), status_code=302,
        )

    state = params.get("state")
    code = params.get("code")
    try:
        pending = gh_oauth.consume_oauth_state(state)
    except ApiError:
        log.warning("github_oauth_bad_state")
        return RedirectResponse(
            gh_oauth.success_redirect(settings, "error"), status_code=302,
        )

    # Reject reuse: consume_oauth_state already deleted the entry.
    if not code:
        return RedirectResponse(
            gh_oauth.success_redirect(settings, "denied"), status_code=302,
        )

    revoked = await db.scalar(
        select(RevokedSession.jti).where(RevokedSession.jti == pending.jti)
    )
    user = await db.get(User, pending.user_id)
    if revoked or user is None or not user.is_active:
        log.warning("github_oauth_stale_session", user_id=pending.user_id)
        return RedirectResponse(
            gh_oauth.success_redirect(settings, "error"), status_code=302,
        )

    try:
        access_token, scopes = await gh_oauth.exchange_code(
            settings, code, pending.code_verifier,
        )
        profile = await gh_oauth.fetch_github_user(access_token)
        await github_accounts.upsert_connection(
            db,
            settings,
            user_id=pending.user_id,
            github_user_id=int(profile["id"]),
            login=str(profile.get("login") or ""),
            avatar_url=profile.get("avatar_url"),
            scopes=scopes,
            access_token=access_token,
        )
    except ApiError:
        log.warning("github_oauth_callback_failed", user_id=pending.user_id)
        return RedirectResponse(
            gh_oauth.success_redirect(settings, "error"), status_code=302,
        )

    return RedirectResponse(
        gh_oauth.success_redirect(settings, "connected"), status_code=302,
    )


@router.delete("/connection", status_code=204)
async def delete_connection(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    _require_oauth(settings)
    await github_accounts.disconnect(db, settings, session.user.id)


@router.get("/repos")
@limiter.limit("30/hour")
async def list_connected_repos(
    request: Request,
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    q: str | None = Query(default=None, max_length=100),
    python_only: bool = Query(default=True),
    page: int = Query(default=1, ge=1, le=100),
) -> dict:
    """Repos the connected user's GitHub repositories for the import picker."""
    _require_oauth(settings)
    token = await github_accounts.access_token_for_user(db, settings, session.user.id)
    if not token:
        raise ApiError(
            401,
            "github_unauthorized",
            "Connect GitHub to import private repositories.",
        )
    try:
        items, has_more = await list_accessible_repos(
            token, page=page, q=q, python_only=python_only,
        )
    except ApiError as exc:
        if exc.code == "github_unauthorized":
            await github_accounts.mark_disconnected_on_unauthorized(db, session.user.id)
        raise
    finally:
        token = None
    return {
        "page": page,
        "per_page": 50,
        "has_more": has_more,
        "items": [
            {
                "owner": row.owner,
                "name": row.name,
                "full_name": row.full_name,
                "html_url": row.html_url,
                "description": row.description,
                "private": row.private,
                "language": row.language,
                "updated_at": row.updated_at,
                "default_branch": row.default_branch,
            }
            for row in items
        ],
    }
