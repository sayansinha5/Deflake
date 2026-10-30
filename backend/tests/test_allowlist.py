from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from app.db.models import Repo
from app.services.allowlist import seed_repos


@pytest.mark.asyncio
async def test_seed_sets_demo_source_and_ready(tmp_path: Path, app_factory):
    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text(
        yaml.dump({
            "repos": [{
                "id": "flaky-shop",
                "name": "flaky-shop",
                "description": "demo",
                "path": "flaky-shop",
                "editable_paths": ["shop/**"],
            }],
        }),
        encoding="utf-8",
    )
    app = await app_factory()
    async with app.state.sessionmaker() as db:
        repos = await seed_repos(db, allowlist)
        await db.commit()
        assert len(repos) == 1
        repo = repos[0]
        assert repo.id == "flaky-shop"
        assert repo.source == "demo"
        assert repo.prepare_status == "ready"
        assert repo.is_private is False


@pytest.mark.asyncio
async def test_seed_keeps_imported_repos(tmp_path: Path, app_factory):
    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text(
        yaml.dump({
            "repos": [{
                "id": "flaky-shop",
                "name": "flaky-shop",
                "description": "demo",
                "path": "flaky-shop",
                "editable_paths": ["shop/**"],
            }],
        }),
        encoding="utf-8",
    )
    app = await app_factory()
    async with app.state.sessionmaker() as db:
        db.add(Repo(
            id="imported-acme-shop",
            name="shop",
            description="",
            path="/repos-data/imported-acme-shop/src",
            source="github_public",
            owner="acme",
            prepare_status="ready",
            test_count=3,
            editable_paths=["src/**", "tests/**"],
        ))
        await db.commit()
        await seed_repos(db, allowlist)
        await db.commit()
        ids = set(await db.scalars(select(Repo.id)))
        assert ids == {"flaky-shop", "imported-acme-shop"}


@pytest.mark.asyncio
async def test_seed_removes_only_stale_demo_repos(tmp_path: Path, app_factory):
    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text(yaml.dump({"repos": []}), encoding="utf-8")
    app = await app_factory()
    async with app.state.sessionmaker() as db:
        db.add(Repo(
            id="old-demo",
            name="old-demo",
            description="",
            path="old-demo",
            source="demo",
            prepare_status="ready",
            test_count=0,
            editable_paths=[],
        ))
        db.add(Repo(
            id="keep-import",
            name="keep",
            description="",
            path="/repos-data/keep-import/src",
            source="github_private",
            owner="acme",
            prepare_status="ready",
            test_count=1,
            editable_paths=["tests/**"],
        ))
        await db.commit()
        await seed_repos(db, allowlist)
        await db.commit()
        ids = set(await db.scalars(select(Repo.id)))
        assert ids == {"keep-import"}
