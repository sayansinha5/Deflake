"""Which repositories a user may see or mutate."""
from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.db.models import Flake, Repo, Run, WorkspaceMember
from app.errors import ApiError

PRIVATE_SOURCE = "github_private"
PUBLIC_SOURCE = "github_public"
DEMO_SOURCE = "demo"


def visible_repo_filter(user_id: str) -> ColumnElement[bool]:
    """
    Visibility:
    - personal demos/imports: only the account that owns them
    - workspace imports: members of that workspace
    """
    member_workspaces = select(WorkspaceMember.workspace_id).where(
        WorkspaceMember.user_id == user_id
    )
    return or_(
        and_(Repo.is_personal.is_(True), Repo.created_by == user_id),
        and_(
            Repo.is_personal.is_(False),
            Repo.workspace_id.is_not(None),
            Repo.workspace_id.in_(member_workspaces),
        ),
        # Legacy rows before is_personal existed may only have created_by.
        and_(Repo.created_by == user_id, Repo.source != DEMO_SOURCE),
    )


def visible_run_filter(user_id: str) -> ColumnElement[bool]:
    """Scans belong to the account that started them — not every viewer of the demo repo."""
    return Run.created_by == user_id


async def get_visible_repo(db: AsyncSession, repo_id: str, user_id: str) -> Repo:
    repo = await db.scalar(
        select(Repo).where(Repo.id == repo_id).where(visible_repo_filter(user_id))
    )
    if repo is None:
        raise ApiError(404, "repo_not_found", "This repository was not found.")
    return repo


async def get_visible_run(db: AsyncSession, run_id: str, user_id: str) -> Run:
    run = await db.scalar(
        select(Run)
        .join(Repo, Repo.id == Run.repo_id)
        .where(Run.id == run_id)
        .where(visible_repo_filter(user_id))
        .where(visible_run_filter(user_id))
    )
    if run is None:
        raise ApiError(404, "run_not_found", "Run not found.")
    return run


async def get_visible_flake(db: AsyncSession, flake_id: str, user_id: str) -> Flake:
    flake = await db.scalar(
        select(Flake)
        .join(Run, Run.id == Flake.run_id)
        .join(Repo, Repo.id == Run.repo_id)
        .where(Flake.id == flake_id)
        .where(visible_repo_filter(user_id))
        .where(visible_run_filter(user_id))
    )
    if flake is None:
        raise ApiError(404, "flake_not_found", "Flake not found.")
    return flake


def assert_can_manage_import(repo: Repo, user_id: str) -> None:
    if repo.source == DEMO_SOURCE:
        raise ApiError(403, "forbidden", "Demo repositories cannot be changed here.")
    if repo.created_by != user_id:
        raise ApiError(
            403, "forbidden", "Only the person who imported this repository can manage it.",
        )
