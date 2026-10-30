"""Which repositories a user may see or mutate."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.db.models import Flake, Repo, Run
from app.errors import ApiError

PRIVATE_SOURCE = "github_private"
PUBLIC_SOURCE = "github_public"
DEMO_SOURCE = "demo"


def visible_repo_filter(user_id: str) -> ColumnElement[bool]:
    """Demo + public imports are workspace-wide; private imports are owner-only."""
    return or_(
        Repo.source != PRIVATE_SOURCE,
        Repo.created_by == user_id,
    )


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
