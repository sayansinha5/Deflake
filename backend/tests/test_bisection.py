"""Polluter bisection with a fake runner: one polluter, an interacting pair, unstable."""
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select

from app.db.models import Diagnosis, Evidence, Flake, LlmCall, Patch, Repo, Run
from app.graph.context import GraphContext, current_context
from app.graph.nodes.bisect import bisect_polluter
from app.graph.run import diagnose_flakes
from app.llm.factory import Llm
from app.services.bisection import SUSPECTED, bisect, failure_count
from app.services.events import empty_steps

VICTIM = "tests/test_pricing.py::test_convert_eur_to_usd"
POLLUTER = "tests/test_pricing.py::test_promo_rate_override"
P1 = "tests/test_a.py::test_p1"
P2 = "tests/test_a.py::test_p2"


class Planted:
    """Fails the victim when the planted polluters are all in the order before it."""

    def __init__(self, polluters: set[str] | None = None, *, alone: int = 0, mode: str = "all"):
        self.polluters = set(polluters or [])
        self.alone = alone
        self.mode = mode
        self.jobs: list[dict] = []

    async def submit(self, job: dict) -> dict:
        self.jobs.append(job)
        order = list(job["order"])
        group = set(order[:-1])
        if not group:
            failures = self.alone
        elif self.mode == "unstable":
            failures = 1
        elif self.mode == "any":
            failures = 3
        elif self.polluters and self.polluters <= group:
            failures = 3
        else:
            failures = 0
        iterations = []
        repeats = int(job["iterations"])
        for index in range(repeats):
            failed = index < failures
            iterations.append({
                "status": "ok",
                "results": [
                    {
                        "test_id": test_id,
                        "outcome": "failed" if failed and test_id == order[-1] else "passed",
                    }
                    for test_id in order
                ],
            })
        return {"iterations": iterations}


def _probe(runner: Planted):
    async def probe(order: list[str]) -> int:
        result = await runner.submit({"order": order, "iterations": 3})
        return failure_count(result, order[-1])

    return probe


def test_failure_count_counts_timeout_failure_and_a_missing_victim():
    victim = "tests/test_a.py::test_v"
    result = {"iterations": [
        {"status": "timeout", "results": []},
        {"status": "ok", "results": [{"test_id": victim, "outcome": "passed"}]},
        {"status": "ok", "results": [{"test_id": victim, "outcome": "failed"}]},
        {"status": "ok", "results": [
            {"test_id": "tests/test_a.py::test_other", "outcome": "failed"},
        ]},
    ]}
    assert failure_count(result, victim) == 3


def test_suspected_categories_cover_the_demo_labels():
    assert {"order_dependent", "shared_resource", "environment"} <= SUSPECTED
    assert "time_dependent" not in SUSPECTED
    assert "randomness" not in SUSPECTED
    assert "async_race" not in SUSPECTED
    assert "hash_order" not in SUSPECTED


async def test_one_planted_polluter_is_isolated():
    prefix = [
        "tests/test_a.py::test_a", "tests/test_a.py::test_b", POLLUTER, "tests/test_a.py::test_c",
    ]
    runner = Planted({POLLUTER})
    result = await bisect(VICTIM, prefix, _probe(runner))
    assert result["status"] == "isolated"
    assert result["polluters"] == [POLLUTER]
    assert result["calls"] < 40
    assert result["steps"][0]["tests"] == [VICTIM]
    assert result["steps"][0]["result"] == "not_reproduced"
    assert result["steps"][-1]["tests"] == [POLLUTER, VICTIM]
    assert result["steps"][-1]["result"] == "reproduced"


async def test_two_interacting_polluters_stay_a_minimal_set():
    prefix = ["tests/test_a.py::test_a", P1, "tests/test_a.py::test_b", P2]
    runner = Planted({P1, P2})
    result = await bisect("tests/test_a.py::test_victim", prefix, _probe(runner))
    assert result["status"] == "isolated"
    assert set(result["polluters"]) == {P1, P2}
    assert len(result["polluters"]) == 2
    assert result["calls"] <= 40
    minimal = {P1, P2, "tests/test_a.py::test_victim"}
    assert any(
        step["result"] == "reproduced" and set(step["tests"]) == minimal
        for step in result["steps"]
    )


async def test_unstable_prefix_is_not_isolated():
    runner = Planted({POLLUTER}, mode="unstable")
    result = await bisect(VICTIM, [POLLUTER, "tests/test_a.py::test_c"], _probe(runner))
    assert result["status"] == "polluter_not_isolated"
    assert result["detail"] == "unstable"
    assert result["polluters"] == []
    assert result["calls"] == 2
    assert [step["result"] for step in result["steps"]] == ["not_reproduced", "not_reproduced"]


async def test_victim_that_fails_alone_stops():
    runner = Planted({POLLUTER}, alone=2)
    result = await bisect(VICTIM, [POLLUTER], _probe(runner))
    assert result["status"] == "not_order_dependent"
    assert result["polluters"] == []
    assert len(runner.jobs) == 1
    assert runner.jobs[0]["order"] == [VICTIM]
    assert result["steps"][0]["result"] == "fails_alone"


async def test_empty_prefix_does_not_call_the_runner():
    runner = Planted({POLLUTER})
    result = await bisect(VICTIM, [], _probe(runner))
    assert result["status"] == "polluter_not_isolated"
    assert result["detail"] == "empty_prefix"
    assert runner.jobs == []


async def test_call_budget_stops_the_search():
    runner = Planted(mode="any")
    result = await bisect(
        VICTIM,
        ["tests/test_a.py::test_a", "tests/test_a.py::test_b", "tests/test_a.py::test_c", POLLUTER],
        _probe(runner),
        budget=3,
    )
    assert result["status"] == "polluter_not_isolated"
    assert result["detail"] == "call_budget"
    assert result["polluters"] == []
    assert result["calls"] == 3


async def test_gate_stops_before_a_probe():
    runner = Planted({POLLUTER})

    async def allow() -> str:
        return "stopped_time"

    result = await bisect(VICTIM, [POLLUTER], _probe(runner), allow=allow)
    assert result["status"] == "stopped_time"
    assert result["calls"] == 0
    assert runner.jobs == []


async def _prepare(
    app, *, category: str, victim: str, iterations: list[list[str]], diagnosed: bool,
):
    from app.db.models import TestOutcome

    async with app.state.sessionmaker() as db:
        repo = await db.get(Repo, "flaky-shop")
        if repo is None:
            db.add(Repo(
                id="flaky-shop", name="flaky-shop", description="", path="flaky-shop",
                test_count=0, editable_paths=["shop/**", "tests/**"],
            ))
        run = Run(
            repo_id="flaky-shop", status="running", config={"time_budget_min": 25},
            steps=empty_steps(),
        )
        db.add(run)
        await db.flush()
        flake = Flake(
            run_id=run.id, test_id=victim, state="diagnosing", category=category,
            fail_count=4, run_count=10, rate=0.4, ci_low=0.12, ci_high=0.74,
        )
        db.add(flake)
        await db.flush()
        samples = []
        for index, order in enumerate(iterations):
            samples.append({
                "iteration": index,
                "hash_seed": 4 + index,
                "outcome": "failed",
                "order_window": order[-2:],
            })
            for position, test_id in enumerate(order):
                db.add(TestOutcome(
                    run_id=run.id, phase="detect", iteration=index, test_id=test_id,
                    outcome="failed" if test_id == victim else "passed",
                    duration_ms=1, seed=index + 1, hash_seed=4 + index, position=position,
                ))
        db.add(Evidence(flake_id=flake.id, failing_samples=samples, passing_samples=[]))
        if diagnosed:
            db.add(Diagnosis(
                flake_id=flake.id, attempt=1, root_cause="cache", mechanism="leaks",
                culprit="shop/pricing.py", category=category, fix_strategy="reset",
                needs_human=False, self_confidence=0.8, agreement_k=3, agreement_n=3,
            ))
            db.add(Patch(
                flake_id=flake.id, attempt=1, diff="--- a/x\n+++ b/x\n", summary="reset",
                status="proposed",
            ))
        await db.commit()
        return run.id, flake.id


def _context(app, runner):
    return GraphContext(
        settings=app.state.settings,
        sessionmaker=app.state.sessionmaker,
        llm=Llm(app.state.settings, session_factory=app.state.sessionmaker),
        search=None,
        runner=runner,
    )


async def test_node_uses_the_full_order_and_pins_the_hash_seed(app):
    decoys = [f"tests/test_a.py::test_d{i}" for i in range(6)]
    order = [POLLUTER, *decoys, VICTIM]
    assert POLLUTER not in order[-2:]
    run_id, flake_id = await _prepare(
        app, category="shared_resource", victim=VICTIM, iterations=[order], diagnosed=False,
    )
    runner = Planted({POLLUTER})
    token = current_context.set(_context(app, runner))
    try:
        await bisect_polluter({"run_id": run_id, "flake_id": flake_id, "test_id": VICTIM})
        await bisect_polluter({"run_id": run_id, "flake_id": flake_id, "test_id": VICTIM})
    finally:
        current_context.reset(token)
    assert runner.jobs[0]["order"] == [VICTIM]
    assert runner.jobs[0]["random_order"] is False
    assert runner.jobs[0]["iterations"] == 3
    assert runner.jobs[0]["hash_seeds"] == [4, 4, 4]
    assert "seeds" not in runner.jobs[0]
    calls = len(runner.jobs)
    assert calls >= 2
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
    assert flake.polluters == [POLLUTER]
    assert flake.bisection["status"] == "isolated"
    assert flake.bisection["calls"] == calls


async def test_node_tries_the_next_failing_order(app):
    victim = "tests/test_settings.py::test_format_price_defaults_to_usd"
    polluter = "tests/test_settings.py::test_currency_from_environment"
    innocent = "tests/test_settings.py::test_explicit_currency_wins"
    run_id, flake_id = await _prepare(
        app, category="environment", victim=victim,
        iterations=[[innocent, victim], [polluter, victim]], diagnosed=False,
    )
    runner = Planted({polluter})
    token = current_context.set(_context(app, runner))
    try:
        await bisect_polluter({"run_id": run_id, "flake_id": flake_id, "test_id": victim})
    finally:
        current_context.reset(token)
    assert [innocent, victim] in [job["order"] for job in runner.jobs]
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
    assert flake.polluters == [polluter]
    assert flake.bisection["status"] == "isolated"
    assert flake.bisection["hash_seed"] == 5


async def test_node_skips_a_category_that_is_not_order_dependent(app):
    run_id, flake_id = await _prepare(
        app, category="randomness", victim=VICTIM, iterations=[[POLLUTER, VICTIM]], diagnosed=False,
    )
    runner = Planted({POLLUTER})
    token = current_context.set(_context(app, runner))
    try:
        await bisect_polluter({"run_id": run_id, "flake_id": flake_id, "test_id": VICTIM})
    finally:
        current_context.reset(token)
    assert runner.jobs == []
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
    assert flake.bisection["status"] == "skipped"
    assert flake.polluters is None


async def test_backfill_bisects_a_diagnosed_flake_without_the_model(app):
    order = [POLLUTER, "tests/test_a.py::test_other", VICTIM]
    run_id, flake_id = await _prepare(
        app, category="shared_resource", victim=VICTIM, iterations=[order], diagnosed=True,
    )
    runner = Planted({POLLUTER})

    class Search:
        calls = 0

        async def search(self, query: str) -> list[dict]:
            self.calls += 1
            return []

    await diagnose_flakes(
        app.state.sessionmaker, app.state.settings, run_id,
        search=Search(), checkpointer=MemorySaver(), runner=runner,
    )
    assert runner.jobs
    async with app.state.sessionmaker() as db:
        flake = await db.get(Flake, flake_id)
        calls = int(await db.scalar(
            select(func.count()).select_from(LlmCall).where(LlmCall.run_id == run_id)
        ) or 0)
        patches = int(await db.scalar(
            select(func.count()).select_from(Patch).where(Patch.flake_id == flake_id)
        ) or 0)
    assert flake.polluters == [POLLUTER]
    assert calls == 0
    assert patches == 1
