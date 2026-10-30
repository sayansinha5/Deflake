from unittest.mock import AsyncMock

import pytest

from app.db.models import Repo
from app.integrations.github.meta import PublicRepoMeta
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
