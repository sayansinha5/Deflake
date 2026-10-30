"""Import, sync and remove GitHub repositories (public URL and connected account)."""
from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    AuditItem,
    Diagnosis,
    Escalation,
    Evidence,
    Flake,
    LlmCall,
    Patch,
    Reference,
    Repo,
    Run,
    RunEvent,
    TestOutcome,
    Verification,
    utcnow,
)
from app.errors import ApiError
from app.integrations.github.meta import NOT_PUBLIC, fetch_public_repo
from app.integrations.github.url import GitHubUrlError, parse_github_repo_url, validate_owner_repo
from app.integrations.github.user_repos import fetch_repo_with_token
from app.preparer_client import PreparerClient
from app.services import github_accounts
from app.services.repo_ids import imported_repo_id
from app.services.repos_access import (
    PRIVATE_SOURCE,
    PUBLIC_SOURCE,
    assert_can_manage_import,
    get_visible_repo,
)
from app.services.run_manager import active_run_for

log = structlog.get_logger()

READY = "ready"
PENDING = "pending"
PREPARING = "preparing"
FAILED = "failed"
NEEDS_RECONNECT = "needs_reconnect"


def _limit_message(settings: Settings) -> str:
    n = settings.max_imported_repos_per_user
    return f"You've reached the limit of {n} imported repositories. Remove one to add another."


async def _imported_count(db: AsyncSession, user_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(Repo).where(
                Repo.created_by == user_id,
                Repo.source.in_((PUBLIC_SOURCE, PRIVATE_SOURCE)),
            )
        )
        or 0
    )


async def find_duplicate(
    db: AsyncSession, owner: str, name: str, user_id: str,
) -> Repo | None:
    """Match an existing import of the same GitHub owner/name visible to this user."""
    rows = list(
        await db.scalars(
            select(Repo).where(
                Repo.source.in_((PUBLIC_SOURCE, PRIVATE_SOURCE)),
                func.lower(Repo.owner) == owner.lower(),
                func.lower(Repo.name) == name.lower(),
            )
        )
    )
    for repo in rows:
        if repo.source == PRIVATE_SOURCE and repo.created_by != user_id:
            continue
        return repo
    return None


def repo_to_path(repo_id: str) -> str:
    return f"/repos-data/{repo_id}/src"


async def import_public_url(
    db: AsyncSession,
    settings: Settings,
    user_id: str,
    url: str,
) -> tuple[Repo, bool]:
    """
    Start a public import. Returns (repo, already_imported).

    Does not wait for prepare; caller schedules prepare_repo in the background.
    """
    if not settings.github_import_enabled:
        raise ApiError(403, "import_disabled", "GitHub repository import is turned off.")

    try:
        parsed = parse_github_repo_url(url)
    except GitHubUrlError as exc:
        raise ApiError(422, "invalid_github_url", str(exc)) from exc

    existing = await find_duplicate(db, parsed.owner, parsed.name, user_id)
    if existing is not None:
        return existing, True

    if await _imported_count(db, user_id) >= settings.max_imported_repos_per_user:
        raise ApiError(409, "import_limit", _limit_message(settings))

    meta = await fetch_public_repo(
        settings, parsed.owner, parsed.name, max_size_mb=settings.repo_max_size_mb,
    )
    if meta.is_private:
        raise ApiError(404, "repo_not_public", NOT_PUBLIC)

    repo_id = imported_repo_id(meta.owner, meta.name)
    # Extremely unlikely collision with a different full name; refuse rather than overwrite.
    clash = await db.get(Repo, repo_id)
    if clash is not None:
        if (
            clash.owner
            and clash.owner.lower() == meta.owner.lower()
            and clash.name.lower() == meta.name.lower()
        ):
            return clash, True
        repo_id = imported_repo_id(f"{meta.owner}-{meta.name}", meta.name)
        if await db.get(Repo, repo_id) is not None:
            raise ApiError(409, "conflict", "Could not allocate an id for this repository.")

    repo = Repo(
        id=repo_id,
        name=meta.name,
        description=meta.description or "",
        path=repo_to_path(repo_id),
        source=PUBLIC_SOURCE,
        owner=meta.owner,
        default_branch=meta.default_branch,
        html_url=meta.html_url,
        is_private=False,
        prepare_status=PENDING,
        prepare_error=None,
        test_count=0,
        editable_paths=[],
        created_by=user_id,
        updated_at=utcnow(),
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return repo, False


async def _require_user_token(
    db: AsyncSession, settings: Settings, user_id: str,
) -> tuple[str, str]:
    """Return (access_token, github_account_id). Raises if not connected."""
    account = await github_accounts.get_active_account(db, user_id)
    if account is None:
        raise ApiError(
            401,
            "github_unauthorized",
            "Connect GitHub to import private repositories.",
        )
    token = await github_accounts.access_token_for_user(db, settings, user_id)
    if not token:
        raise ApiError(
            401,
            "github_unauthorized",
            "Connect GitHub to import private repositories.",
        )
    return token, account.id


async def import_from_github(
    db: AsyncSession,
    settings: Settings,
    user_id: str,
    owner: str,
    name: str,
) -> tuple[Repo, bool, str | None]:
    """
    Import a repo visible to the connected GitHub account.

    Returns (repo, already_imported, prepare_token).
    prepare_token is set for private repos (and cleared by the caller after schedule).
    """
    if not settings.github_import_enabled:
        raise ApiError(403, "import_disabled", "GitHub repository import is turned off.")
    if not settings.github_oauth_enabled:
        raise ApiError(403, "oauth_disabled", "GitHub OAuth is turned off.")

    try:
        parsed = validate_owner_repo(owner, name)
    except GitHubUrlError as exc:
        raise ApiError(422, "invalid_github_url", str(exc)) from exc

    existing = await find_duplicate(db, parsed.owner, parsed.name, user_id)
    if existing is not None:
        return existing, True, None

    if await _imported_count(db, user_id) >= settings.max_imported_repos_per_user:
        raise ApiError(409, "import_limit", _limit_message(settings))

    try:
        token, account_id = await _require_user_token(db, settings, user_id)
        meta = await fetch_repo_with_token(
            token, parsed.owner, parsed.name, max_size_mb=settings.repo_max_size_mb,
        )
    except ApiError as exc:
        if exc.code == "github_unauthorized":
            await github_accounts.mark_disconnected_on_unauthorized(db, user_id)
        raise

    repo_id = imported_repo_id(meta.owner, meta.name)
    clash = await db.get(Repo, repo_id)
    if clash is not None:
        if (
            clash.owner
            and clash.owner.lower() == meta.owner.lower()
            and clash.name.lower() == meta.name.lower()
        ):
            # Private clash owned by someone else is invisible via find_duplicate;
            # refuse colliding public id.
            if clash.source == PRIVATE_SOURCE and clash.created_by != user_id:
                repo_id = imported_repo_id(f"{meta.owner}-u{user_id[:8]}", meta.name)
                if await db.get(Repo, repo_id) is not None:
                    raise ApiError(409, "conflict", "Could not allocate an id for this repository.")
            else:
                return clash, True, None
        else:
            repo_id = imported_repo_id(f"{meta.owner}-{meta.name}", meta.name)
            if await db.get(Repo, repo_id) is not None:
                raise ApiError(409, "conflict", "Could not allocate an id for this repository.")

    source = PRIVATE_SOURCE if meta.is_private else PUBLIC_SOURCE
    prepare_token = token if meta.is_private else None
    repo = Repo(
        id=repo_id,
        name=meta.name,
        description=meta.description or "",
        path=repo_to_path(repo_id),
        source=source,
        owner=meta.owner,
        default_branch=meta.default_branch,
        html_url=meta.html_url,
        is_private=meta.is_private,
        github_account_id=account_id if meta.is_private else None,
        prepare_status=PENDING,
        prepare_error=None,
        test_count=0,
        editable_paths=[],
        created_by=user_id,
        updated_at=utcnow(),
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return repo, False, prepare_token


async def sync_import(
    db: AsyncSession,
    settings: Settings,
    user_id: str,
    repo_id: str,
) -> tuple[Repo, str | None]:
    """Returns (repo, prepare_token_or_none)."""
    repo = await get_visible_repo(db, repo_id, user_id)
    assert_can_manage_import(repo, user_id)
    if repo.source not in {PUBLIC_SOURCE, PRIVATE_SOURCE}:
        raise ApiError(403, "forbidden", "Only imported repositories can be synced.")
    if await active_run_for(db, repo.id) is not None:
        raise ApiError(
            409, "run_already_active",
            "A scan of this repository is already running. Wait for it to finish.",
        )
    if not repo.owner:
        raise ApiError(422, "invalid_request", "This repository has no GitHub owner.")

    prepare_token: str | None = None
    if repo.source == PUBLIC_SOURCE:
        await fetch_public_repo(
            settings, repo.owner, repo.name, max_size_mb=settings.repo_max_size_mb,
        )
    else:
        if repo.prepare_status == NEEDS_RECONNECT:
            raise ApiError(
                401,
                "github_unauthorized",
                "GitHub connection expired. Reconnect to continue.",
            )
        try:
            token, account_id = await _require_user_token(db, settings, user_id)
            meta = await fetch_repo_with_token(
                token, repo.owner, repo.name, max_size_mb=settings.repo_max_size_mb,
            )
        except ApiError as exc:
            if exc.code == "github_unauthorized":
                await github_accounts.mark_disconnected_on_unauthorized(db, user_id)
            raise
        repo.default_branch = meta.default_branch or repo.default_branch
        repo.html_url = meta.html_url or repo.html_url
        repo.is_private = meta.is_private
        repo.github_account_id = account_id
        prepare_token = token

    repo.prepare_status = PENDING
    repo.prepare_error = None
    repo.updated_at = utcnow()
    await db.commit()
    await db.refresh(repo)
    return repo, prepare_token


async def _delete_scan_data(db: AsyncSession, repo_id: str) -> None:
    """Delete every scan of this repository and the rows that hang off those scans."""
    run_ids = list(await db.scalars(select(Run.id).where(Run.repo_id == repo_id)))
    if not run_ids:
        return

    flake_ids = list(await db.scalars(select(Flake.id).where(Flake.run_id.in_(run_ids))))
    if flake_ids:
        patch_ids = list(await db.scalars(select(Patch.id).where(Patch.flake_id.in_(flake_ids))))
        diagnosis_ids = list(
            await db.scalars(select(Diagnosis.id).where(Diagnosis.flake_id.in_(flake_ids)))
        )
        await db.execute(
            update(AuditItem).where(AuditItem.flake_id.in_(flake_ids)).values(flake_id=None)
        )
        if diagnosis_ids:
            await db.execute(
                update(AuditItem)
                .where(AuditItem.diagnosis_id.in_(diagnosis_ids))
                .values(diagnosis_id=None)
            )
        if patch_ids:
            await db.execute(
                update(AuditItem).where(AuditItem.patch_id.in_(patch_ids)).values(patch_id=None)
            )
            await db.execute(delete(Verification).where(Verification.patch_id.in_(patch_ids)))
        await db.execute(delete(Escalation).where(Escalation.flake_id.in_(flake_ids)))
        await db.execute(delete(Evidence).where(Evidence.flake_id.in_(flake_ids)))
        await db.execute(delete(Reference).where(Reference.flake_id.in_(flake_ids)))
        await db.execute(delete(Diagnosis).where(Diagnosis.flake_id.in_(flake_ids)))
        await db.execute(delete(Patch).where(Patch.flake_id.in_(flake_ids)))
        await db.execute(delete(LlmCall).where(LlmCall.flake_id.in_(flake_ids)))

    await db.execute(delete(LlmCall).where(LlmCall.run_id.in_(run_ids)))
    await db.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
    await db.execute(delete(TestOutcome).where(TestOutcome.run_id.in_(run_ids)))
    await db.execute(delete(Flake).where(Flake.run_id.in_(run_ids)))

    for run_id in run_ids:
        pattern = f"{run_id}:%"
        await db.execute(
            text("DELETE FROM checkpoint_writes WHERE thread_id LIKE :pattern"),
            {"pattern": pattern},
        )
        await db.execute(
            text("DELETE FROM checkpoint_blobs WHERE thread_id LIKE :pattern"),
            {"pattern": pattern},
        )
        await db.execute(
            text("DELETE FROM checkpoints WHERE thread_id LIKE :pattern"),
            {"pattern": pattern},
        )

    await db.execute(delete(Run).where(Run.id.in_(run_ids)))


async def remove_import(
    db: AsyncSession,
    settings: Settings,
    preparer: PreparerClient,
    user_id: str,
    repo_id: str,
) -> None:
    repo = await get_visible_repo(db, repo_id, user_id)
    assert_can_manage_import(repo, user_id)
    if repo.source not in {PUBLIC_SOURCE, PRIVATE_SOURCE}:
        raise ApiError(403, "forbidden", "Demo repositories cannot be removed here.")
    if await active_run_for(db, repo.id) is not None:
        raise ApiError(
            409, "run_already_active",
            "This repository cannot be removed while a scan is running.",
        )
    await _delete_scan_data(db, repo.id)
    try:
        await preparer.cleanup(repo.id)
    except ApiError as exc:
        # Still delete the DB row if the workspace is already gone.
        if exc.code not in {"preparer_unreachable", "preparer_error"}:
            log.warning("preparer_cleanup_failed", repo_id=repo.id, code=exc.code)
    await db.delete(repo)
    await db.commit()


async def prepare_repo(
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    preparer: PreparerClient,
    repo_id: str,
    *,
    token: str | None = None,
) -> None:
    async with maker() as db:
        repo = await db.get(Repo, repo_id)
        if repo is None:
            return
        repo.prepare_status = PREPARING
        repo.prepare_error = None
        repo.updated_at = utcnow()
        await db.commit()
        owner = repo.owner
        name = repo.name
        branch = repo.default_branch
        clone_url = f"https://github.com/{owner}/{name}.git"

    job = {
        "repo_id": repo_id,
        "clone_url": clone_url,
        "branch": branch,
        "max_size_mb": settings.repo_max_size_mb,
        "clone_timeout_s": settings.repo_clone_timeout_s,
        "prepare_timeout_s": settings.prepare_timeout_s,
    }
    if token:
        job["token"] = token

    try:
        result = await preparer.prepare(job)
    except ApiError as exc:
        async with maker() as db:
            repo = await db.get(Repo, repo_id)
            if repo is None:
                return
            repo.prepare_status = FAILED
            repo.prepare_error = exc.message
            repo.updated_at = utcnow()
            await db.commit()
        return
    finally:
        job.pop("token", None)
        token = None

    async with maker() as db:
        repo = await db.get(Repo, repo_id)
        if repo is None:
            return
        if result.get("status") == "ready":
            repo.prepare_status = READY
            repo.prepare_error = None
            repo.commit_sha = result.get("commit_sha")
            repo.default_branch = result.get("default_branch") or repo.default_branch
            repo.test_count = int(result.get("test_count") or 0)
            repo.editable_paths = list(result.get("editable_paths") or [])
            repo.last_prepared_at = utcnow()
        else:
            repo.prepare_status = FAILED
            repo.prepare_error = result.get("error") or "Prepare failed."
        repo.updated_at = utcnow()
        await db.commit()


def schedule_prepare(
    app_state,
    settings: Settings,
    repo_id: str,
    *,
    token: str | None = None,
) -> None:
    asyncio.create_task(
        prepare_repo(
            app_state.sessionmaker, settings, app_state.preparer, repo_id, token=token,
        )
    )
