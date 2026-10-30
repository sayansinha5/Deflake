"""Pull-request preview and create (GitHub API mocked)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet

from app.db.models import (
    Diagnosis,
    Flake,
    GithubAccount,
    Patch,
    Repo,
    Run,
    Verification,
    new_id,
    utcnow,
)
from app.integrations.github.git_data import CreatedPullRequest, RepoPermissions, branch_name_for
from app.security.token_crypto import encrypt_token
from app.services import github_prs
from tests.conftest import CSRF, MEMBER_EMAIL, MEMBER_PASSWORD, add_user, client_for, sign_in

FERNET_KEY = Fernet.generate_key().decode()


def _oauth():
    return {
        "github_oauth_enabled": True,
        "github_oauth_client_id": "client",
        "github_oauth_client_secret": "secret",
        "github_token_encryption_key": FERNET_KEY,
    }


def test_branch_name_is_stable_and_safe():
    name = branch_name_for("tests/test_checkout.py::test_applies_discount", "abcd1234-ffff")
    assert name.startswith("deflake/fix-")
    assert "abcd1234" in name
    assert " " not in name
    assert "/" in name  # prefix slash only in deflake/fix-...


async def _seed_verified(app, user_id: str, *, routing: str = "auto_pr"):
    settings = app.state.settings
    async with app.state.sessionmaker() as db:
        account = GithubAccount(
            id=new_id(),
            user_id=user_id,
            github_user_id=42,
            login="dev",
            avatar_url=None,
            scopes="repo",
            access_token_encrypted=encrypt_token(settings, "gho_pr_token"),
            connected_at=utcnow(),
        )
        db.add(account)
        await db.flush()
        repo = Repo(
            id="gh-pr-demo",
            name="demo",
            description="",
            path="/repos-data/gh-pr-demo/src",
            source="github_public",
            owner="acme",
            default_branch="main",
            html_url="https://github.com/acme/demo",
            is_private=False,
            commit_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            prepare_status="ready",
            created_by=user_id,
            test_count=1,
            editable_paths=["."],
        )
        db.add(repo)
        await db.flush()
        run = Run(
            id=new_id(),
            repo_id=repo.id,
            status="completed",
            config={},
            steps={},
            created_by=user_id,
        )
        db.add(run)
        await db.flush()
        flake = Flake(
            id=new_id(),
            run_id=run.id,
            test_id="tests/test_x.py::test_flaky",
            state="detected",
            category="order_dependent",
            fail_count=4,
            run_count=30,
            rate=0.13,
            ci_low=0.04,
            ci_high=0.3,
            routing=routing,
        )
        db.add(flake)
        await db.flush()
        db.add(Diagnosis(
            id=new_id(),
            flake_id=flake.id,
            attempt=1,
            root_cause="Shared module state from an earlier test.",
            mechanism="Mutation",
            culprit="tests/test_setup.py::test_boot",
            category="order_dependent",
            fix_strategy="Isolate state",
            self_confidence=0.9,
            agreement_k=3,
            agreement_n=3,
        ))
        patch = Patch(
            id=new_id(),
            flake_id=flake.id,
            attempt=1,
            diff="--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n",
            summary="Isolate state",
            status="verified",
            files_changed=["x.py"],
            lines_changed=1,
        )
        db.add(patch)
        await db.flush()
        db.add(Verification(
            id=new_id(),
            patch_id=patch.id,
            reruns=200,
            failures=0,
            ub95=0.02,
            power_ok=True,
            full_suite_passed=True,
            outcome="verified",
        ))
        await db.commit()
        return flake.id


@pytest.mark.asyncio
async def test_preview_requires_push_access(app_factory):
    app = await app_factory(**_oauth())
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    flake_id = await _seed_verified(app, user.id)

    with (
        patch(
            "app.services.github_prs.git_data.fetch_permissions",
            new=AsyncMock(return_value=RepoPermissions(
                push=False, default_branch="main",
                full_name="acme/demo", html_url="https://github.com/acme/demo",
            )),
        ),
        patch(
            "app.services.github_prs.git_data.fetch_branch_tip",
            new=AsyncMock(return_value="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        ),
    ):
        async with client_for(app) as client:
            await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
            response = await client.get(f"/api/flakes/{flake_id}/pull-request")
    assert response.status_code == 200
    body = response.json()
    assert body["can_create"] is False
    assert "write access" in body["disabled_reason"]


@pytest.mark.asyncio
async def test_create_pull_request_calls_git_data(app_factory):
    app = await app_factory(**_oauth())
    user = await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    flake_id = await _seed_verified(app, user.id)

    created = CreatedPullRequest(
        number=7,
        html_url="https://github.com/acme/demo/pull/7",
        branch="deflake/fix-test_flaky-deadbeef",
        head_sha="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    with (
        patch(
            "app.services.github_prs.git_data.fetch_permissions",
            new=AsyncMock(return_value=RepoPermissions(
                push=True, default_branch="main",
                full_name="acme/demo", html_url="https://github.com/acme/demo",
            )),
        ),
        patch(
            "app.services.github_prs.git_data.fetch_branch_tip",
            new=AsyncMock(return_value="cccccccccccccccccccccccccccccccccccccccc"),
        ),
        patch(
            "app.services.github_prs.git_data.create_pull_request_from_diff",
            new=AsyncMock(return_value=created),
        ) as create,
    ):
        async with client_for(app) as client:
            await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
            response = await client.post(
                f"/api/flakes/{flake_id}/pull-request", headers=CSRF,
            )
    assert response.status_code == 200
    body = response.json()
    assert body["number"] == 7
    assert body["html_url"].endswith("/pull/7")
    create.assert_awaited()
    kwargs = create.await_args.kwargs
    assert kwargs["owner"] == "acme"
    assert kwargs["name"] == "demo"
    assert "default branch" in kwargs["body"].lower() or "moved" in kwargs["body"].lower()
    assert "Generated by Deflake" in kwargs["body"]


def test_pr_body_includes_rates_and_footer():
    flake = Flake(
        id="f1",
        run_id="r1",
        test_id="t::name",
        state="detected",
        category="race",
        fail_count=3,
        run_count=30,
        rate=0.1,
        ci_low=0.02,
        ci_high=0.25,
    )
    diagnosis = Diagnosis(
        id="d1", flake_id="f1", attempt=1,
        root_cause="A race on shared cache.",
        mechanism="m", culprit="c", category="race",
        fix_strategy="s", self_confidence=0.8, agreement_k=2, agreement_n=3,
    )
    verification = Verification(
        id="v1", patch_id="p1", reruns=200, failures=0, ub95=0.015,
        power_ok=True, full_suite_passed=True, outcome="verified",
    )
    body = github_prs.build_pr_body(
        flake=flake,
        diagnosis=diagnosis,
        verification=verification,
        references=[],
        scanned_sha="abc123def456",
        default_branch="main",
        default_tip="abc123def456",
    )
    assert "A race on shared cache." in body
    assert "200 randomized reruns" in body
    assert "abc123def456"[:12] in body
