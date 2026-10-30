from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.db.models import Evidence, Flake, Repo, Run
from app.integrations.github.meta import PublicRepoMeta
from app.services.events import empty_steps
from tests.conftest import CSRF, MEMBER_EMAIL, MEMBER_PASSWORD, add_user, client_for, sign_in


def _meta(owner="hukkin", name="tomli") -> PublicRepoMeta:
    return PublicRepoMeta(
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        html_url=f"https://github.com/{owner}/{name}",
        description="demo",
        default_branch="master",
        size_kb=100,
        is_private=False,
    )


@pytest.mark.asyncio
async def test_import_rejects_bad_url(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    response = await client.post(
        "/api/repos/import",
        headers=CSRF,
        json={"url": "https://gitlab.com/acme/shop"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_github_url"


@pytest.mark.asyncio
async def test_import_creates_pending_repo_and_schedules_prepare(app_factory, monkeypatch):
    app = await app_factory()
    scheduled: list[str] = []

    async def fake_fetch(settings, owner, name, *, max_size_mb):
        return _meta(owner, name)

    def fake_schedule(state, settings, repo_id, *, token=None):
        scheduled.append(repo_id)

    monkeypatch.setattr("app.services.import_repos.fetch_public_repo", fake_fetch)
    monkeypatch.setattr("app.services.import_repos.schedule_prepare", fake_schedule)

    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    async with client_for(app) as client:
        await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        response = await client.post(
            "/api/repos/import",
            headers=CSRF,
            json={"url": "https://github.com/hukkin/tomli"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["already_imported"] is False
    assert body["source"] == "github_public"
    assert body["owner"] == "hukkin"
    assert body["name"] == "tomli"
    assert body["prepare_status"] == "pending"
    assert scheduled == [body["id"]]


@pytest.mark.asyncio
async def test_duplicate_import_returns_existing(app_factory, monkeypatch):
    app = await app_factory()
    monkeypatch.setattr(
        "app.services.import_repos.fetch_public_repo",
        AsyncMock(return_value=_meta()),
    )
    monkeypatch.setattr("app.services.import_repos.schedule_prepare", lambda *a, **k: None)

    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    async with client_for(app) as client:
        await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        first = await client.post(
            "/api/repos/import", headers=CSRF, json={"url": "https://github.com/hukkin/tomli"},
        )
        second = await client.post(
            "/api/repos/import", headers=CSRF, json={"url": "https://github.com/hukkin/tomli.git"},
        )
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["already_imported"] is True


@pytest.mark.asyncio
async def test_start_scan_refuses_unready_import(app, client):
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    fields = {
        "id": "imported-demo",
        "name": "demo",
        "description": "",
        "path": "/repos-data/imported-demo/src",
        "source": "github_public",
        "owner": "acme",
        "prepare_status": "preparing",
        "test_count": 0,
        "editable_paths": [],
        "created_by": None,
    }
    async with app.state.sessionmaker() as db:
        db.add(Repo(**fields))
        await db.commit()
    response = await client.post("/api/repos/imported-demo/runs", headers=CSRF, json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "repo_not_ready"


async def _imported_repo(app, user_id: str, repo_id: str = "imported-removable") -> Repo:
    fields = {
        "id": repo_id,
        "name": "removable",
        "description": "",
        "path": f"/repos-data/{repo_id}/src",
        "source": "github_public",
        "owner": "acme",
        "prepare_status": "ready",
        "test_count": 1,
        "editable_paths": ["src/**"],
        "created_by": user_id,
    }
    async with app.state.sessionmaker() as db:
        repo = Repo(**fields)
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
        return repo


@pytest.mark.asyncio
async def test_remove_imported_repo_deletes_finished_scans(app, client):
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    repo = await _imported_repo(app, user.id)
    async with app.state.sessionmaker() as db:
        run = Run(
            repo_id=repo.id,
            status="completed",
            config={"detect_reruns": 30},
            steps=empty_steps(),
        )
        db.add(run)
        await db.flush()
        flake = Flake(
            run_id=run.id,
            test_id="tests/test_x.py::test_y",
            state="flaky",
            fail_count=2,
            run_count=30,
            rate=0.07,
            ci_low=0.01,
            ci_high=0.2,
        )
        db.add(flake)
        await db.flush()
        db.add(Evidence(
            flake_id=flake.id,
            failing_samples=[{"iteration": 1}],
            passing_samples=[{"iteration": 2}],
        ))
        await db.commit()
        run_id = run.id
        flake_id = flake.id
    app.state.preparer.cleanup = AsyncMock(return_value=None)

    response = await client.delete(f"/api/repos/{repo.id}", headers=CSRF)
    assert response.status_code == 204

    async with app.state.sessionmaker() as db:
        assert await db.get(Repo, repo.id) is None
        assert await db.get(Run, run_id) is None
        assert await db.get(Flake, flake_id) is None
        assert await db.get(Evidence, flake_id) is None
        remaining = int(
            await db.scalar(select(func.count()).select_from(Run).where(Run.repo_id == repo.id))
            or 0
        )
        assert remaining == 0
    app.state.preparer.cleanup.assert_awaited_once_with(repo.id)


@pytest.mark.asyncio
async def test_remove_imported_repo_blocked_while_scan_running(app, client):
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    repo = await _imported_repo(app, user.id, repo_id="imported-busy")
    async with app.state.sessionmaker() as db:
        db.add(Run(
            repo_id=repo.id,
            status="running",
            config={"detect_reruns": 30},
            steps=empty_steps(),
        ))
        await db.commit()
    app.state.preparer.cleanup = AsyncMock(return_value=None)

    response = await client.delete(f"/api/repos/{repo.id}", headers=CSRF)
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "run_already_active"
    assert "cannot be removed while a scan is running" in body["message"]

    async with app.state.sessionmaker() as db:
        assert await db.get(Repo, repo.id) is not None
    app.state.preparer.cleanup.assert_not_awaited()
