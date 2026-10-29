"""Escalation providers, idempotency, fallback, and the evidence bundle."""
import json

import httpx
from sqlalchemy import select

from app.db.models import Diagnosis, Escalation, Evidence, Flake, Patch, Repo, Run, Verification
from app.graph.context import GraphContext, current_context
from app.graph.nodes.escalate import escalate
from app.integrations.escalation.github import GitHubIssueProvider
from app.integrations.escalation.local import LocalProvider
from app.integrations.escalation.tendem import (
    TendemProvider,
    extract_task_id,
    map_status,
)
from app.llm.factory import Llm
from app.services.escalation import deliver, split_summary
from app.services.events import empty_steps
from tests.conftest import CSRF, MEMBER_EMAIL, MEMBER_PASSWORD, add_user, sign_in
from tests.test_config import build

TEST_ID = "tests/test_reports.py::test_daily_sales_summary_is_fast"
DIFF = "--- a/shop/reports.py\n+++ b/shop/reports.py\n@@ -1 +1 @@\n-x\n+y\n"


def test_summary_keeps_one_question():
    summary, question = split_summary("The cache leaks.\nQuestion: Reset it where?")
    assert "cache" in summary
    assert question == "Reset it where?"
    _summary, fallback = split_summary("No question line here.")
    assert fallback.startswith("What is the smallest change")


def test_task_id_and_status_come_from_the_documented_payload():
    task_id = "11111111-1111-4111-8111-111111111111"
    assert extract_task_id({"structuredContent": {"task_id": task_id}}) == task_id
    as_text = {"content": [{"type": "text", "text": json.dumps({"task_id": task_id})}]}
    assert extract_task_id(as_text) == task_id
    waiting = {"structuredContent": {"next_action": "await_user_approval", "status": "scoping"}}
    assert map_status(waiting) == "in_progress"
    ready = {"structuredContent": {"next_action": "fetch_result"}}
    assert map_status(ready) == "resolved"
    assert map_status({"content": [{"text": "still scoping"}]}) == "submitted"


async def test_tendem_submit_sends_only_create_task_fields():
    seen = {}

    async def tool(name, arguments):
        seen["name"] = name
        seen["arguments"] = arguments
        return {"structuredContent": {"task_id": "11111111-1111-4111-8111-111111111111"}}

    provider = TendemProvider(build(tendem_api_key=None), tool=tool)
    result = await provider.submit(
        {"app": "Deflake", "test_id": TEST_ID, "text": "bundle text"},
        "flake:1",
    )
    assert seen["name"] == "create_task"
    assert set(seen["arguments"]) == {"name", "description", "conversation_id"}
    assert seen["arguments"]["conversation_id"] == "flake:1"
    assert seen["arguments"]["description"] == "bundle text"
    assert "approve" not in seen["name"]
    assert result.provider == "tendem"
    assert result.external_ref == "11111111-1111-4111-8111-111111111111"


async def test_github_issue_uses_the_documented_rest_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/repos/acme/shop/issues"
            body = json.loads(request.content)
            assert body["title"].startswith("Deflake:")
            assert "bundle text" in body["body"]
            return httpx.Response(201, json={"number": 12, "state": "open"})
        assert request.url.path == "/repos/acme/shop/issues/12"
        return httpx.Response(200, json={"state": "closed"})

    settings = build(github_token="test-token", github_repo="acme/shop", tendem_api_key=None)
    provider = GitHubIssueProvider(settings, transport=httpx.MockTransport(handler))
    created = await provider.submit(
        {"app": "Deflake", "test_id": TEST_ID, "text": "bundle text"}, "k",
    )
    assert created.external_ref == "12"
    status = await provider.status("12")
    assert status.status == "resolved"


class _Down:
    name = "tendem"

    def __init__(self) -> None:
        self.calls = 0

    async def submit(self, bundle, idempotency_key):
        self.calls += 1
        raise TimeoutError("down")

    async def status(self, external_ref):
        raise TimeoutError("down")


async def test_two_failures_fall_back_to_local():
    down = _Down()
    result, attempts = await deliver({}, "flake:1", down, LocalProvider())
    assert down.calls == 2
    assert result.provider == "local"
    assert result.external_ref == "local:flake:1"
    assert [item["ok"] for item in attempts] == [False, False, True]
    assert attempts[0]["error"] == "TimeoutError"


def _context(app):
    return GraphContext(
        settings=app.state.settings,
        sessionmaker=app.state.sessionmaker,
        llm=Llm(app.state.settings, session_factory=app.state.sessionmaker),
        search=None,
        runner=None,
    )


async def _routed(app, *, routing: str):
    async with app.state.sessionmaker() as db:
        if await db.get(Repo, "flaky-shop") is None:
            db.add(Repo(
                id="flaky-shop", name="flaky-shop", description="", path="flaky-shop",
                test_count=0, editable_paths=["shop/**", "tests/**"],
            ))
        run = Run(
            repo_id="flaky-shop", status="completed",
            config={"time_budget_min": 25}, steps=empty_steps(),
        )
        db.add(run)
        await db.flush()
        flake = Flake(
            run_id=run.id, test_id=TEST_ID, state="escalated", category="time_dependent",
            routing=routing, fail_count=1, run_count=40, rate=0.025, ci_low=0.0, ci_high=0.13,
            confidence_raw=0.595, confidence_cal=0.595,
        )
        db.add(flake)
        await db.flush()
        db.add(Diagnosis(
            flake_id=flake.id, attempt=1, root_cause="The budget is tight.",
            mechanism="Load makes the assertion fail.", culprit="shop/reports.py",
            category="time_dependent", fix_strategy="Ask a person.",
            needs_human=False, self_confidence=0.4, agreement_k=2, agreement_n=3,
        ))
        db.add(Evidence(
            flake_id=flake.id,
            failing_samples=[{
                "outcome": "failed",
                "traceback": "token sk-secretvalue123456 in /home/meera/proj/shop/reports.py",
            }],
            passing_samples=[{"outcome": "passed", "traceback": None}],
        ))
        patch = Patch(
            flake_id=flake.id, attempt=2, diff=DIFF, summary="widen the budget",
            status="failed_verify", lines_changed=4,
        )
        db.add(patch)
        await db.flush()
        db.add(Verification(
            patch_id=patch.id, reruns=40, failures=1, power_ok=False,
            full_suite_passed=None, outcome="inconclusive",
        ))
        await db.commit()
        return run.id, flake.id


async def _escalate(app, run_id, flake_id):
    token = current_context.set(_context(app))
    try:
        await escalate({"run_id": run_id, "flake_id": flake_id, "test_id": TEST_ID})
    finally:
        current_context.reset(token)


async def test_duplicate_submit_stores_one_redacted_bundle(app):
    run_id, flake_id = await _routed(app, routing="escalate")
    await _escalate(app, run_id, flake_id)
    await _escalate(app, run_id, flake_id)
    async with app.state.sessionmaker() as db:
        rows = list(await db.scalars(select(Escalation).where(Escalation.flake_id == flake_id)))
    assert len(rows) == 1
    row = rows[0]
    assert row.idempotency_key == f"{flake_id}:1"
    assert row.provider == "local"
    assert row.external_ref == f"local:{flake_id}:1"
    assert [item["ok"] for item in row.attempts] == [False, False, True]
    assert row.attempts[0]["provider"] == "tendem"
    dumped = json.dumps(row.bundle)
    assert "sk-" not in dumped
    assert "/home/meera" not in dumped
    assert "[redacted]" in dumped
    assert row.bundle["question"]
    assert row.bundle["verification"]["outcome"] == "inconclusive"
    assert row.bundle["verification"]["failures"] == 1


async def test_auto_pr_is_not_submitted(app):
    run_id, flake_id = await _routed(app, routing="auto_pr")
    await _escalate(app, run_id, flake_id)
    async with app.state.sessionmaker() as db:
        count = await db.scalar(select(Escalation.id).where(Escalation.flake_id == flake_id))
    assert count is None


async def test_list_refresh_and_bundle_download(app, client):
    run_id, flake_id = await _routed(app, routing="escalate")
    await _escalate(app, run_id, flake_id)
    hidden = await client.get("/api/escalations")
    assert hidden.status_code == 401
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    listed = await client.get("/api/escalations")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["test_id"] == TEST_ID
    assert body[0]["provider"] == "local"
    refreshed = await client.post(
        f"/api/escalations/{body[0]['id']}/refresh", headers=CSRF,
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "submitted"
    downloaded = await client.get(f"/api/flakes/{flake_id}/bundle")
    assert downloaded.status_code == 200
    assert "attachment" in downloaded.headers["content-disposition"]
    assert json.loads(downloaded.text)["test_id"] == TEST_ID
    missing = await client.get(
        "/api/flakes/00000000-0000-0000-0000-000000000000/bundle",
    )
    assert missing.status_code == 404
