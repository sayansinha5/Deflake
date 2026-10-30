"""Private imports are visible only to the importing user."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from app.db.models import Flake, GithubAccount, Repo, Run, new_id, utcnow
from app.integrations.github.user_repos import AuthedRepoMeta
from app.security.token_crypto import encrypt_token
from tests.conftest import (
    CSRF,
    MEMBER_EMAIL,
    MEMBER_PASSWORD,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    add_user,
    client_for,
    sign_in,
)

FERNET_KEY = Fernet.generate_key().decode()


def _oauth_overrides():
    return {
        "github_oauth_enabled": True,
        "github_oauth_client_id": "client",
        "github_oauth_client_secret": "secret",
        "github_token_encryption_key": FERNET_KEY,
    }


async def _seed_private(app, owner_user_id: str) -> tuple[str, str, str]:
    """Create private repo + run + flake owned by owner_user_id. Returns repo_id, run_id, flake_id."""
    settings = app.state.settings
    async with app.state.sessionmaker() as db:
        account = GithubAccount(
            id=new_id(),
            user_id=owner_user_id,
            github_user_id=1001,
            login="owner-gh",
            avatar_url=None,
            scopes="repo",
            access_token_encrypted=encrypt_token(settings, "gho_seed_token"),
            connected_at=utcnow(),
        )
        db.add(account)
        await db.flush()
        repo = Repo(
            id="priv-seed",
            name="secret-shop",
            description="private",
            path="/repos-data/priv-seed/src",
            source="github_private",
            owner="owner-gh",
            is_private=True,
            github_account_id=account.id,
            prepare_status="ready",
            created_by=owner_user_id,
            test_count=1,
            editable_paths=[],
        )
        db.add(repo)
        await db.flush()
        run = Run(
            id=new_id(),
            repo_id=repo.id,
            status="completed",
            config={"detect_reruns": 30},
            steps={},
            created_by=owner_user_id,
        )
        db.add(run)
        await db.flush()
        flake = Flake(
            id=new_id(),
            run_id=run.id,
            test_id="tests/test_x.py::test_y",
            state="detected",
            fail_count=3,
            run_count=30,
            rate=0.1,
            ci_low=0.02,
            ci_high=0.3,
        )
        db.add(flake)
        await db.commit()
        return repo.id, run.id, flake.id


@pytest.mark.asyncio
async def test_second_user_cannot_see_private_repo_run_or_flake(app_factory):
    app = await app_factory(**_oauth_overrides())
    owner = await add_user(app, OWNER_EMAIL, OWNER_PASSWORD, role="owner")
    member = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD, role="member")
    repo_id, run_id, flake_id = await _seed_private(app, owner.id)

    async with client_for(app) as as_owner:
        await sign_in(as_owner, OWNER_EMAIL, OWNER_PASSWORD)
        repos = (await as_owner.get("/api/repos")).json()
        assert any(r["id"] == repo_id for r in repos)
        assert (await as_owner.get(f"/api/repos/{repo_id}")).status_code == 200
        assert (await as_owner.get(f"/api/runs/{run_id}")).status_code == 200
        assert (await as_owner.get(f"/api/flakes/{flake_id}")).status_code == 200
        assert (await as_owner.get(f"/api/flakes/{flake_id}/patch")).status_code in {200, 404}

    async with client_for(app) as as_member:
        await sign_in(as_member, MEMBER_EMAIL, MEMBER_PASSWORD)
        repos = (await as_member.get("/api/repos")).json()
        assert all(r["id"] != repo_id for r in repos)
        assert (await as_member.get(f"/api/repos/{repo_id}")).status_code == 404
        assert (await as_member.get(f"/api/runs/{run_id}")).status_code == 404
        runs = (await as_member.get("/api/runs")).json()
        assert all(item["id"] != run_id for item in runs["items"])
        assert (await as_member.get(f"/api/flakes/{flake_id}")).status_code == 404
        assert (await as_member.get(f"/api/flakes/{flake_id}/patch")).status_code == 404
        # member id unused except to prove two users exist
        assert member.id != owner.id


@pytest.mark.asyncio
async def test_import_from_github_private_schedules_with_token(app_factory, monkeypatch):
    app = await app_factory(**_oauth_overrides())
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    settings = app.state.settings
    async with app.state.sessionmaker() as db:
        db.add(GithubAccount(
            id=new_id(),
            user_id=user.id,
            github_user_id=55,
            login="member-gh",
            avatar_url=None,
            scopes="repo",
            access_token_encrypted=encrypt_token(settings, "gho_import_token"),
            connected_at=utcnow(),
        ))
        await db.commit()

    scheduled: list[tuple[str, str | None]] = []

    async def fake_fetch(token, owner, name, *, max_size_mb):
        assert token == "gho_import_token"
        return AuthedRepoMeta(
            owner=owner,
            name=name,
            full_name=f"{owner}/{name}",
            html_url=f"https://github.com/{owner}/{name}",
            description="",
            default_branch="main",
            size_kb=10,
            is_private=True,
        )

    def fake_schedule(state, settings, repo_id, *, token=None):
        scheduled.append((repo_id, token))

    monkeypatch.setattr("app.services.import_repos.fetch_repo_with_token", fake_fetch)
    monkeypatch.setattr("app.services.import_repos.schedule_prepare", fake_schedule)

    async with client_for(app) as client:
        await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        response = await client.post(
            "/api/repos/import/github",
            headers=CSRF,
            json={"owner": "member-gh", "name": "hidden"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "github_private"
    assert body["is_private"] is True
    assert body["prepare_status"] == "pending"
    assert scheduled == [(body["id"], "gho_import_token")]


@pytest.mark.asyncio
async def test_list_github_repos_requires_connection(app_factory, monkeypatch):
    app = await app_factory(**_oauth_overrides())
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    monkeypatch.setattr(
        "app.api.github_oauth.list_accessible_repos",
        AsyncMock(return_value=([], False)),
    )
    async with client_for(app) as client:
        await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        response = await client.get("/api/github/repos")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "github_unauthorized"
