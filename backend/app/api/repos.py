from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db
from app.db.models import Repo, Run
from app.schemas.runs import RepoOut

router = APIRouter(prefix="/repos", tags=["repos"])


@router.get("", response_model=list[RepoOut])
async def list_repos(
    _user: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> list[RepoOut]:
    repos = list(await db.scalars(select(Repo).order_by(Repo.name)))
    latest: dict[str, Run] = {}
    if repos:
        runs = list(await db.scalars(
            select(Run).where(Run.repo_id.in_([r.id for r in repos]))
            .order_by(Run.created_at.desc())
        ))
        for run in runs:
            latest.setdefault(run.repo_id, run)
    return [
        RepoOut(
            id=r.id, name=r.name, description=r.description, test_count=r.test_count,
            last_scan_at=(latest[r.id].finished_at or latest[r.id].started_at)
            if r.id in latest else None,
            last_result=latest[r.id].status if r.id in latest else None,
        )
        for r in repos
    ]
