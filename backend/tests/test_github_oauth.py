"""GitHub OAuth state, token crypto, and connection API (no live GitHub)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet

from app.db.models import GithubAccount, Repo, new_id, utcnow
from app.integrations.github import oauth as gh_oauth
from app.security.token_crypto import decrypt_token, encrypt_token
from app.services import github_accounts
from tests.conftest import CSRF, MEMBER_EMAIL, MEMBER_PASSWORD, add_user, sign_in

FERNET_KEY = Fernet.generate_key().decode()


def _oauth_overrides(**extra):
    return {
        "github_oauth_enabled": True,
        "github_oauth_client_id": "test-client",
        "github_oauth_client_secret": "test-secret",
        "github_token_encryption_key": FERNET_KEY,
        **extra,
    }


@pytest.fixture(autouse=True)
def _clear_oauth_states():
    gh_oauth.clear_oauth_states()
    yield
    gh_oauth.clear_oauth_states()


def test_oauth_state_is_single_use():
    state, challenge = gh_oauth.create_oauth_state("user-1", "jti-1")
    assert challenge
    first = gh_oauth.consume_oauth_state(state)
    assert first.user_id == "user-1"
    assert first.jti == "jti-1"
    with pytest.raises(Exception) as raised:
        gh_oauth.consume_oauth_state(state)
    assert raised.value.code == "oauth_state_invalid"


def test_oauth_state_rejects_missing_and_unknown():
    with pytest.raises(Exception) as missing:
        gh_oauth.consume_oauth_state(None)
    assert missing.value.code == "oauth_state_invalid"
    with pytest.raises(Exception) as unknown:
        gh_oauth.consume_oauth_state("no-such-state")
    assert unknown.value.code == "oauth_state_invalid"


def test_success_redirect_never_uses_request_url():
    from types import SimpleNamespace

    settings = SimpleNamespace(
        github_oauth_success_url="http://localhost:5173/settings/integration",
    )
    url = gh_oauth.success_redirect(settings, "connected")
    assert url.endswith("github=connected")
    assert url.startswith("http://localhost:5173/settings/integration")


def test_fernet_roundtrip_and_corrupt():
    from types import SimpleNamespace

    from pydantic import SecretStr

    settings = SimpleNamespace(github_token_encryption_key=SecretStr(FERNET_KEY))
    blob = encrypt_token(settings, "gho_test_token_value")
    assert "gho_test_token_value" not in blob
    assert decrypt_token(settings, blob) == "gho_test_token_value"
    with pytest.raises(Exception) as raised:
        decrypt_token(settings, "not-a-fernet-token")
    assert raised.value.code == "oauth_token_corrupt"


async def test_connection_endpoints_hide_token(app_factory):
    app = await app_factory(**_oauth_overrides())
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    from tests.conftest import client_for

    async with client_for(app) as client:
        await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        settings = app.state.settings
        async with app.state.sessionmaker() as db:
            account = GithubAccount(
                id=new_id(),
                user_id=user.id,
                github_user_id=4242,
                login="octo-test",
                avatar_url=None,
                scopes="repo read:user",
                access_token_encrypted=encrypt_token(settings, "gho_secret_must_not_leak"),
                connected_at=utcnow(),
            )
            db.add(account)
            await db.commit()

        settings_view = (await client.get("/api/settings")).json()
        connection = (await client.get("/api/github/connection")).json()
        raw = str(settings_view) + str(connection)
        assert "gho_secret_must_not_leak" not in raw
        assert "access_token" not in raw
        assert settings_view["github"]["connected"] is True
        assert settings_view["github"]["login"] == "octo-test"
        assert connection["connected"] is True
        assert connection["login"] == "octo-test"
        assert connection["oauth_enabled"] is True


async def test_oauth_start_redirects_when_enabled(app_factory):
    app = await app_factory(**_oauth_overrides())
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    from tests.conftest import client_for

    async with client_for(app) as client:
        await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        response = await client.get("/api/github/oauth/start", follow_redirects=False)
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("https://github.com/login/oauth/authorize?")
        assert "client_id=test-client" in location
        assert "code_challenge=" in location
        assert "state=" in location


async def test_oauth_start_disabled(app_factory):
    app = await app_factory(github_oauth_enabled=False)
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    from tests.conftest import client_for

    async with client_for(app) as client:
        await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        response = await client.get("/api/github/oauth/start", follow_redirects=False)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "oauth_disabled"


async def test_oauth_callback_rejects_state_reuse(app_factory):
    app = await app_factory(**_oauth_overrides())
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    state, _challenge = gh_oauth.create_oauth_state(user.id, "jti-live")
    from tests.conftest import client_for

    async with client_for(app) as client:
        # First hit consumes state (exchange fails without a mock → error redirect).
        await client.get(
            f"/api/github/oauth/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        second = await client.get(
            f"/api/github/oauth/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert second.status_code == 302
        assert "github=error" in second.headers["location"]


async def test_oauth_callback_stores_encrypted_token(app_factory):
    app = await app_factory(**_oauth_overrides())
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    state, _challenge = gh_oauth.create_oauth_state(user.id, "jti-ok")
    from tests.conftest import client_for

    with (
        patch.object(
            gh_oauth, "exchange_code",
            new=AsyncMock(return_value=("gho_live_token", "repo read:user")),
        ),
        patch.object(
            gh_oauth, "fetch_github_user",
            new=AsyncMock(return_value={
                "id": 99, "login": "demo-gh", "avatar_url": "https://example.test/a.png",
            }),
        ),
    ):
        async with client_for(app) as client:
            response = await client.get(
                f"/api/github/oauth/callback?code=good&state={state}",
                follow_redirects=False,
            )
            assert response.status_code == 302
            assert "github=connected" in response.headers["location"]

    async with app.state.sessionmaker() as db:
        account = await github_accounts.get_active_account(db, user.id)
        assert account is not None
        assert account.login == "demo-gh"
        assert "gho_live_token" not in account.access_token_encrypted
        assert decrypt_token(app.state.settings, account.access_token_encrypted) == "gho_live_token"


async def test_disconnect_marks_private_repos_and_revokes(app_factory):
    app = await app_factory(**_oauth_overrides())
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    from tests.conftest import client_for

    async with client_for(app) as client:
        await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        settings = app.state.settings
        async with app.state.sessionmaker() as db:
            account = GithubAccount(
                id=new_id(),
                user_id=user.id,
                github_user_id=7,
                login="leave-me",
                avatar_url=None,
                scopes="repo",
                access_token_encrypted=encrypt_token(settings, "gho_to_revoke"),
                connected_at=utcnow(),
            )
            db.add(account)
            db.add(Repo(
                id="private-demo",
                name="private-demo",
                description="",
                path="private-demo",
                source="github_private",
                owner="leave-me",
                is_private=True,
                github_account_id=account.id,
                prepare_status="ready",
                created_by=user.id,
            ))
            await db.commit()

        with patch.object(gh_oauth, "revoke_token", new=AsyncMock()) as revoke:
            response = await client.delete("/api/github/connection", headers=CSRF)
            assert response.status_code == 204
            revoke.assert_awaited()

        connection = (await client.get("/api/github/connection")).json()
        assert connection["connected"] is False
        async with app.state.sessionmaker() as db:
            repo = await db.get(Repo, "private-demo")
            assert repo.prepare_status == "needs_reconnect"
            assert repo.github_account_id is None
            assert await github_accounts.get_active_account(db, user.id) is None
