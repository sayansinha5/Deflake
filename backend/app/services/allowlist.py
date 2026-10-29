from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Repo, utcnow

ALLOWED_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"


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


async def seed_repos(session: AsyncSession, path: Path) -> list[Repo]:
    listed = load_yaml(path)
    existing = {r.id: r for r in (await session.scalars(select(Repo))).all()}
    keep = set()
    for item in listed:
        keep.add(item["id"])
        repo = existing.get(item["id"])
        if repo is None:
            repo = Repo(id=item["id"], test_count=0)
            session.add(repo)
        repo.name = item["name"]
        repo.description = item["description"]
        repo.path = item["path"]
        repo.editable_paths = item["editable_paths"]
        repo.updated_at = utcnow()
    for repo_id, repo in existing.items():
        if repo_id not in keep:
            await session.delete(repo)
    await session.flush()
    return list((await session.scalars(select(Repo).order_by(Repo.name))).all())
