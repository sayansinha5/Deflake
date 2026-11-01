from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Repo, utcnow
from app.services.repo_ids import demo_repo_id_for_user

DEMO_SOURCE = "demo"
READY = "ready"


def load_yaml(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    repos = data.get("repos") or []
    if not isinstance(repos, list):
        raise ValueError("allowlist.yaml: 'repos' must be a list")
    seen: set[str] = set()
    out = []
    for item in repos:
        repo_id = str(item["id"])
        if repo_id in seen:
            raise ValueError(f"allowlist.yaml: duplicate id {repo_id}")
        seen.add(repo_id)
        out.append({
            "id": repo_id,
            "name": str(item.get("name") or repo_id),
            "description": str(item.get("description") or ""),
            "path": str(item["path"]),
            "editable_paths": list(item.get("editable_paths") or []),
        })
    return out


def allowlist_file(settings: Settings) -> Path:
    path = Path(settings.allowlist_path)
    if path.is_absolute():
        return path
    # settings path is relative to the backend package root in compose.
    return Path(__file__).resolve().parents[2] / path


def runner_repo_key(repo: Repo) -> str:
    """Key the runner uses to find source on disk (demo folder name, else DB id)."""
    if repo.source == DEMO_SOURCE:
        return repo.path
    return repo.id


async def seed_repos(session: AsyncSession, path: Path) -> list[Repo]:
    """
    Refresh metadata on personal demo repos from allowlist.yaml.

    Does not create a shared demo row. Per-user demos are created by
    ensure_demo_repos_for_user. Removes obsolete shared demos (no owner) and
    demos whose path is no longer in the allowlist.
    """
    templates = load_yaml(path)
    by_path = {item["path"]: item for item in templates}
    existing = list(
        await session.scalars(select(Repo).where(Repo.source == DEMO_SOURCE))
    )
    for repo in existing:
        # Legacy shared demos (no owner) stay in the DB but are no longer visible.
        if repo.created_by is None:
            continue
        template = by_path.get(repo.path)
        if template is None:
            await session.delete(repo)
            continue
        repo.name = template["name"]
        repo.description = template["description"]
        repo.editable_paths = template["editable_paths"]
        repo.source = DEMO_SOURCE
        repo.is_private = False
        repo.is_personal = True
        repo.workspace_id = None
        repo.prepare_status = READY
        repo.prepare_error = None
        repo.github_account_id = None
        repo.owner = None
        repo.html_url = None
        repo.updated_at = utcnow()
    await session.flush()
    return list(
        await session.scalars(
            select(Repo).where(Repo.source == DEMO_SOURCE).order_by(Repo.name)
        )
    )


async def ensure_demo_repos_for_user(
    session: AsyncSession,
    settings: Settings,
    user_id: str,
) -> list[Repo]:
    """Attach a fresh personal copy of each allowlist demo to the account."""
    path = allowlist_file(settings)
    if not path.is_file():
        return []
    templates = load_yaml(path)
    owned = list(
        await session.scalars(
            select(Repo).where(
                Repo.source == DEMO_SOURCE,
                Repo.created_by == user_id,
            )
        )
    )
    by_path = {repo.path: repo for repo in owned}
    created: list[Repo] = []
    for item in templates:
        if item["path"] in by_path:
            continue
        repo_id = demo_repo_id_for_user(item["id"], user_id)
        clash = await session.get(Repo, repo_id)
        if clash is not None:
            continue
        repo = Repo(
            id=repo_id,
            name=item["name"],
            description=item["description"],
            path=item["path"],
            editable_paths=item["editable_paths"],
            source=DEMO_SOURCE,
            created_by=user_id,
            is_personal=True,
            workspace_id=None,
            prepare_status=READY,
            prepare_error=None,
            test_count=0,
            is_private=False,
        )
        session.add(repo)
        created.append(repo)
        by_path[item["path"]] = repo
    if created:
        await session.flush()
    return created
