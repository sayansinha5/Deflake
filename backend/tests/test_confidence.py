"""Confidence weights, routing overrides, verification outcomes, and patch download."""
import pytest
from sqlalchemy import select

from app.db.models import (
    CalibrationVersion,
    Diagnosis,
    Flake,
    Patch,
    Reference,
    Repo,
    Run,
    Verification,
)
from app.errors import ApiError
from app.graph.context import GraphContext, current_context
from app.graph.nodes.score import route, score_confidence
from app.graph.nodes.verify import verify
from app.llm.factory import Llm
from app.services.confidence import (
    apply_calibration,
    decide_route,
    minimality,
    raw_confidence,
)
from app.services.events import empty_steps
from tests.conftest import CSRF, MEMBER_EMAIL, MEMBER_PASSWORD, add_user, sign_in

VICTIM = "tests/test_pricing.py::test_convert_eur_to_usd"
DIFF = "--- a/shop/pricing.py\n+++ b/shop/pricing.py\n@@ -1 +1 @@\n-x\n+y\n"


def test_raw_score_uses_the_stated_weights():
    score, parts = raw_confidence(
        agreement_k=2, agreement_n=3, outcome="verified", lines_changed=50,
        first_attempt_clean=False, self_confidence=0.5, reference_matched=True,
    )
    assert parts["minimality"]["value"] == pytest.approx(0.5)
    assert parts["verification"]["value"] == 1
    assert parts["guardrail"]["value"] == 0
    expected = 0.30 * (2 / 3) + 0.30 + 0.15 * 0.5 + 0.10 * 0.5 + 0.05
    assert score == pytest.approx(expected)
    assert minimality(10) == 1
    assert minimality(80) == 0
    assert minimality(100) == 0


def test_underpowered_proof_is_half_and_never_auto_pr():
    score, parts = raw_confidence(
        agreement_k=3, agreement_n=3, outcome="underpowered", lines_changed=4,
        first_attempt_clean=True, self_confidence=1, reference_matched=True,
    )
    assert parts["verification"]["value"] == 0.5
    assert decide_route(
        outcome="underpowered", category="order_dependent", needs_human=False,
        score=score, threshold=0.8,
    ) == "escalate"


@pytest.mark.parametrize("outcome,category,needs_human,score,expected", [
    ("verified", "environment", False, 0.99, "escalate"),
    ("verified", "order_dependent", True, 0.99, "escalate"),
    ("inconclusive", "order_dependent", False, 0.99, "escalate"),
    ("verified", "order_dependent", False, 0.79, "escalate"),
    ("verified", "order_dependent", False, 0.80, "auto_pr"),
])
def test_routing_overrides(outcome, category, needs_human, score, expected):
    assert decide_route(
        outcome=outcome, category=category, needs_human=needs_human,
        score=score, threshold=0.80,
    ) == expected


def test_calibration_maps_a_raw_score_and_ignores_an_empty_fit():
    assert apply_calibration(0.4, None) == pytest.approx(0.4)
    points = [{"raw": 0.0, "calibrated": 0.2}, {"raw": 1.0, "calibrated": 0.4}]
    mapped = apply_calibration(0.5, points)
    assert mapped == pytest.approx(0.3)


class SuiteRunner:
    def __init__(
        self, *, fail_target: bool = False, fail_other: bool = False, reject: bool = False,
    ):
        self.fail_target = fail_target
        self.fail_other = fail_other
        self.reject = reject
        self.jobs: list[dict] = []

    async def submit(self, job: dict) -> dict:
        if self.reject:
            raise ApiError(422, "patch_rejected", "does not apply")
        self.jobs.append(job)
        iterations = []
        for index in range(job["iterations"]):
            other = "failed" if self.fail_other else "passed"
            target = "failed" if self.fail_target else "passed"
            iterations.append({
                "index": index, "status": "ok",
                "results": [
                    {"test_id": VICTIM, "outcome": target},
                    {"test_id": "tests/test_a.py::test_ok", "outcome": other},
                ],
            })
        return {"iterations": iterations}


def _context(app, runner):
    return GraphContext(
        settings=app.state.settings,
        sessionmaker=app.state.sessionmaker,
        llm=Llm(app.state.settings, session_factory=app.state.sessionmaker),
        search=None,
        runner=runner,
    )


async def _flake(
    app, *, category="order_dependent", ci_low=0.2, needs_human=False, patch=True, reruns=40,
):
    async with app.state.sessionmaker() as db:
        if await db.get(Repo, "flaky-shop") is None:
            db.add(Repo(
                id="flaky-shop", name="flaky-shop", description="", path="flaky-shop",
                test_count=0, editable_paths=["shop/**", "tests/**"],
            ))
        run = Run(
            repo_id="flaky-shop", status="completed",
            config={"time_budget_min": 25, "verify_reruns": reruns}, steps=empty_steps(),
        )
        db.add(run)
        await db.flush()
        flake = Flake(
            run_id=run.id, test_id=VICTIM, state="patching", category=category,
            fail_count=6, run_count=30, rate=0.2, ci_low=ci_low, ci_high=0.4,
        )
        db.add(flake)
        await db.flush()
        db.add(Diagnosis(
            flake_id=flake.id, attempt=1, root_cause="cache", mechanism="leaks",
            culprit="shop/pricing.py", category=category, fix_strategy="reset",
            needs_human=needs_human, self_confidence=0.9, agreement_k=3, agreement_n=3,
        ))
        db.add(Reference(
            flake_id=flake.id, title="note", url="https://example.test/issue",
            site="example.test", snippet="cache", matched=True,
        ))
        if patch:
            db.add(Patch(
                flake_id=flake.id, attempt=1, diff=DIFF, summary="reset",
                status="proposed", lines_changed=4,
            ))
        await db.commit()
        return run.id, flake.id


async def _finish(app, runner, run_id, flake_id):
    state = {"run_id": run_id, "flake_id": flake_id, "test_id": VICTIM}
    token = current_context.set(_context(app, runner))
    try:
        await verify(state)
        await score_confidence(state)
        await route(state)
    finally:
        current_context.reset(token)


async def test_zero_failures_and_a_green_suite_verify_and_auto_pr(app):
    run_id, flake_id = await _flake(app)
    runner = SuiteRunner()
    await _finish(app, runner, run_id, flake_id)
    assert sum(job["iterations"] for job in runner.jobs if job["random_order"]) == 40
    assert runner.jobs[-1]["random_order"] is False
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
        row = await db.scalar(select(Verification).join(
            Patch, Verification.patch_id == Patch.id,
        ).where(Patch.flake_id == flake_id))
    assert row.outcome == "verified"
    assert row.failures == 0
    assert row.power_ok is True
    assert row.full_suite_passed is True
    assert flake.state == "auto_pr"
    assert flake.routing == "auto_pr"
    assert flake.confidence_cal == flake.confidence_raw


async def test_a_target_failure_stops_early_and_escalates(app):
    run_id, flake_id = await _flake(app, reruns=80)
    runner = SuiteRunner(fail_target=True)
    await _finish(app, runner, run_id, flake_id)
    assert len(runner.jobs) == 1
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
        patch = await db.scalar(select(Patch).where(Patch.flake_id == flake_id))
        row = await db.scalar(select(Verification).where(Verification.patch_id == patch.id))
    assert row.outcome == "inconclusive"
    assert row.failures > 0
    assert row.reruns == 40
    assert patch.status == "failed_verify"
    assert flake.routing == "escalate"
    assert flake.state == "escalated"


async def test_a_new_failure_is_a_regression(app):
    run_id, flake_id = await _flake(app)
    runner = SuiteRunner(fail_other=True)
    await _finish(app, runner, run_id, flake_id)
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
        row = await db.scalar(select(Verification).join(
            Patch, Verification.patch_id == Patch.id,
        ).where(Patch.flake_id == flake_id))
    assert row.full_suite_passed is False
    assert "tests/test_a.py::test_ok" in row.regressions
    assert flake.routing == "escalate"


async def test_underpowered_cap_is_not_verified(app):
    app.state.settings.verify_reruns_max = 80
    run_id, flake_id = await _flake(app, ci_low=0.001)
    runner = SuiteRunner()
    await _finish(app, runner, run_id, flake_id)
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
        row = await db.scalar(select(Verification).join(
            Patch, Verification.patch_id == Patch.id,
        ).where(Patch.flake_id == flake_id))
    assert row.outcome == "underpowered"
    assert row.reruns == 80
    assert row.power_ok is False
    assert flake.state == "escalated"
    assert flake.routing == "escalate"


async def test_environment_flake_is_escalated_without_the_runner(app):
    run_id, flake_id = await _flake(app, category="environment", needs_human=True, patch=False)
    runner = SuiteRunner()
    await _finish(app, runner, run_id, flake_id)
    assert runner.jobs == []
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
    assert flake.routing == "escalate"
    assert flake.state == "escalated"


async def test_active_calibration_can_hold_a_fix_below_the_threshold(app):
    run_id, flake_id = await _flake(app)
    async with app.state.sessionmaker() as db:
        db.add(CalibrationVersion(
            method="isotonic",
            points=[{"raw": 0.0, "calibrated": 0.1}, {"raw": 1.0, "calibrated": 0.2}],
            threshold=0.9, n_labels=30, reason="test fit",
        ))
        await db.commit()
    await _finish(app, SuiteRunner(), run_id, flake_id)
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
    assert flake.confidence_cal < flake.confidence_raw
    assert flake.confidence_cal < 0.9
    assert flake.routing == "escalate"


async def test_patch_download_and_auth(app, client):
    _run_id, flake_id = await _flake(app)
    missing = await client.get(f"/api/flakes/{flake_id}/patch")
    assert missing.status_code == 401
    await add_user(app, MEMBER_EMAIL, MEMBER_PASSWORD)
    await sign_in(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    downloaded = await client.get(f"/api/flakes/{flake_id}/patch", headers=CSRF)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("text/x-diff")
    assert "attachment" in downloaded.headers["content-disposition"]
    assert downloaded.text == DIFF
    absent = await client.get(
        "/api/flakes/00000000-0000-0000-0000-000000000000/patch", headers=CSRF,
    )
    assert absent.status_code == 404
