from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from app.db.models import Repo, User
from app.services.allowlist import ensure_demo_repos_for_user, seed_repos
from app.services.repo_ids import demo_repo_id_for_user
from tests.conftest import make_settings


@pytest.mark.asyncio
async def test_ensure_creates_personal_demo(tmp_path: Path, app_factory, monkeypatch):
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
    settings = make_settings(allowlist_path=str(allowlist))
    app = await app_factory(allowlist_path=str(allowlist))
    async with app.state.sessionmaker() as db:
        user = User(
            email="demo-owner@example.test",
            full_name="Demo Owner",
            password_hash="x",
            role="member",
        )
        db.add(user)
        await db.flush()
        created = await ensure_demo_repos_for_user(db, settings, user.id)
        await db.commit()
        assert len(created) == 1
        repo = created[0]
        assert repo.id == demo_repo_id_for_user("flaky-shop", user.id)
        assert repo.source == "demo"
        assert repo.created_by == user.id
        assert repo.is_personal is True
        assert repo.prepare_status == "ready"
        assert repo.test_count == 0
        assert repo.path == "flaky-shop"


@pytest.mark.asyncio
async def test_seed_refreshes_personal_demo_metadata(tmp_path: Path, app_factory):
    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text(
        yaml.dump({
            "repos": [{
                "id": "flaky-shop",
                "name": "flaky-shop",
                "description": "updated description",
                "path": "flaky-shop",
                "editable_paths": ["shop/**", "tests/**"],
            }],
        }),
        encoding="utf-8",
    )
    app = await app_factory()
    async with app.state.sessionmaker() as db:
        user = User(
            email="seed-user@example.test",
            full_name="Seed",
            password_hash="x",
            role="member",
        )
        db.add(user)
        await db.flush()
        repo_id = demo_repo_id_for_user("flaky-shop", user.id)
        db.add(Repo(
            id=repo_id,
            name="flaky-shop",
            description="old",
            path="flaky-shop",
            source="demo",
            created_by=user.id,
            is_personal=True,
            prepare_status="ready",
            test_count=0,
            editable_paths=["shop/**"],
        ))
        await db.commit()
        repos = await seed_repos(db, allowlist)
        await db.commit()
        assert len(repos) == 1
        assert repos[0].description == "updated description"
        assert repos[0].editable_paths == ["shop/**", "tests/**"]


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
        assert ids == {"imported-acme-shop"}


@pytest.mark.asyncio
async def test_seed_removes_only_stale_owned_demo_repos(tmp_path: Path, app_factory):
    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text(yaml.dump({"repos": []}), encoding="utf-8")
    app = await app_factory()
    async with app.state.sessionmaker() as db:
        user = User(
            email="stale@example.test",
            full_name="Stale",
            password_hash="x",
            role="member",
        )
        db.add(user)
        await db.flush()
        db.add(Repo(
            id="old-demo-u12345678",
            name="old-demo",
            description="",
            path="old-demo",
            source="demo",
            created_by=user.id,
            is_personal=True,
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
