from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep
from app.config import Settings
from app.db.models import Repo, Run
from app.errors import ApiError
from app.schemas.runs import REPO_ID, ImportGithubRepoIn, ImportRepoIn, ImportRepoOut, RepoOut
from app.security.ratelimit import limiter
from app.services import import_repos
from app.services.repos_access import get_visible_repo, visible_repo_filter

router = APIRouter(prefix="/repos", tags=["repos"])


def _repo_out(repo: Repo, latest: dict[str, Run]) -> RepoOut:
    last = latest.get(repo.id)
    return RepoOut(
        id=repo.id,
        name=repo.name,
        description=repo.description,
        source=repo.source,
        owner=repo.owner,
        html_url=repo.html_url,
        is_private=repo.is_private,
        commit_sha=repo.commit_sha,
        prepare_status=repo.prepare_status,
        prepare_error=repo.prepare_error,
        test_count=repo.test_count,
        last_scan_at=(last.finished_at or last.started_at) if last else None,
        last_result=last.status if last else None,
        last_prepared_at=repo.last_prepared_at,
        default_branch=repo.default_branch,
    )


async def _latest_by_repo(db: AsyncSession, repos: list[Repo]) -> dict[str, Run]:
    latest: dict[str, Run] = {}
    if not repos:
        return latest
    runs = list(await db.scalars(
        select(Run).where(Run.repo_id.in_([r.id for r in repos]))
        .order_by(Run.created_at.desc())
    ))
    for run in runs:
        latest.setdefault(run.repo_id, run)
    return latest


@router.get("", response_model=list[RepoOut])
async def list_repos(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> list[RepoOut]:
    repos = list(await db.scalars(
        select(Repo).where(visible_repo_filter(session.user.id)).order_by(Repo.name)
    ))
    latest = await _latest_by_repo(db, repos)
    return [_repo_out(r, latest) for r in repos]


@router.post("/import", response_model=ImportRepoOut)
@limiter.limit("10/hour")
async def import_public_repo(
    request: Request,
    body: ImportRepoIn,
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> ImportRepoOut:
    repo, already = await import_repos.import_public_url(
        db, settings, session.user.id, body.url,
    )
    if not already:
        import_repos.schedule_prepare(request.app.state, settings, repo.id)
    latest = await _latest_by_repo(db, [repo])
    base = _repo_out(repo, latest)
    return ImportRepoOut(**base.model_dump(), already_imported=already)


@router.post("/import/github", response_model=ImportRepoOut)
@limiter.limit("10/hour")
async def import_github_repo(
    request: Request,
    body: ImportGithubRepoIn,
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> ImportRepoOut:
    repo, already, token = await import_repos.import_from_github(
        db, settings, session.user.id, body.owner, body.name,
    )
    try:
        if not already:
            import_repos.schedule_prepare(
                request.app.state, settings, repo.id, token=token,
            )
    finally:
        token = None
    latest = await _latest_by_repo(db, [repo])
    base = _repo_out(repo, latest)
    return ImportRepoOut(**base.model_dump(), already_imported=already)


@router.post("/{repo_id}/sync", response_model=RepoOut)
@limiter.limit("20/hour")
async def sync_repo(
    request: Request,
    repo_id: str = Path(pattern=REPO_ID),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> RepoOut:
    if not settings.github_import_enabled:
        raise ApiError(403, "import_disabled", "GitHub repository import is turned off.")
    repo, token = await import_repos.sync_import(db, settings, session.user.id, repo_id)
    try:
        import_repos.schedule_prepare(
            request.app.state, settings, repo.id, token=token,
        )
    finally:
        token = None
    latest = await _latest_by_repo(db, [repo])
    return _repo_out(repo, latest)


@router.delete("/{repo_id}", status_code=204)
@limiter.limit("20/hour")
async def delete_repo(
    request: Request,
    repo_id: str = Path(pattern=REPO_ID),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    await import_repos.remove_import(
        db, settings, request.app.state.preparer, session.user.id, repo_id,
    )


@router.get("/{repo_id}", response_model=RepoOut)
async def get_repo(
    repo_id: str = Path(pattern=REPO_ID),
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> RepoOut:
    repo = await get_visible_repo(db, repo_id, session.user.id)
    latest = await _latest_by_repo(db, [repo])
    return _repo_out(repo, latest)
