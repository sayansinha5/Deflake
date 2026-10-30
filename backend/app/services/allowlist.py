from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Repo, utcnow

ALLOWED_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"
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


async def seed_repos(session: AsyncSession, path: Path) -> list[Repo]:
    """Upsert demo repos from allowlist.yaml. Never deletes imported GitHub repos."""
    listed = load_yaml(path)
    existing = {r.id: r for r in (await session.scalars(select(Repo))).all()}
    keep = {item["id"] for item in listed}
    for item in listed:
        repo = existing.get(item["id"])
        if repo is None:
            repo = Repo(id=item["id"], test_count=0)
            session.add(repo)
        elif repo.source != DEMO_SOURCE:
            # An imported repo must not share an allowlist id.
            raise ValueError(
                f"allowlist.yaml: id {item['id']!r} collides with an imported repository"
            )
        repo.name = item["name"]
        repo.description = item["description"]
        repo.path = item["path"]
        repo.editable_paths = item["editable_paths"]
        repo.source = DEMO_SOURCE
        repo.is_private = False
        repo.prepare_status = READY
        repo.prepare_error = None
        repo.github_account_id = None
        repo.owner = None
        repo.html_url = None
        repo.updated_at = utcnow()
    for repo_id, repo in existing.items():
        if repo.source == DEMO_SOURCE and repo_id not in keep:
            await session.delete(repo)
    await session.flush()
    return list((await session.scalars(select(Repo).order_by(Repo.name))).all())
