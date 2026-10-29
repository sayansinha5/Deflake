from decimal import Decimal

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select

from app.db.models import (
    Diagnosis,
    Escalation,
    Evidence,
    Flake,
    LlmCall,
    Patch,
    Reference,
    Repo,
    Run,
    SearchCache,
)
from app.graph.agreement import majority
from app.graph.context import GraphContext, current_context
from app.graph.nodes.classify import classify
from app.graph.nodes.diagnose import diagnose
from app.graph.nodes.escalate import escalate
from app.graph.nodes.patch import patch
from app.graph.nodes.research import research
from app.graph.run import diagnose_flakes
from app.graph.text import clean_query
from app.integrations.tavily import cached_search
from app.llm.factory import Llm
from app.llm.schemas import DiagnoseOut
from app.services.events import empty_steps


class FakeSearch:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self.queries: list[str] = []

    async def search(self, query: str) -> list[dict]:
        self.calls += 1
        self.queries.append(query)
        if self.fail:
            raise TimeoutError("tavily down")
        return [{
            "title": "Stale cache between tests",
            "url": "https://example.test/issue",
            "content": "A module-level cache leaks into the next test.",
            "score": 0.4,
        }]


def _sample(category: str, culprit: str, confidence: float) -> DiagnoseOut:
    return DiagnoseOut(
        root_cause="cause", mechanism="how", culprit=culprit, evidence_refs=["failing-1"],
        category=category, fix_strategy="reset it", needs_human=False, confidence=confidence,
    )


def test_majority_keeps_the_largest_group():
    chosen, size = majority([
        _sample("order_dependent", "shop/pricing.py::_rate_cache", 0.4),
        _sample("hash_order", "shop/reports.py::total", 0.9),
        _sample("order_dependent", "shop/pricing.py::_rate_cache", 0.7),
    ])
    assert size == 2
    assert chosen.category == "order_dependent"
    assert chosen.confidence == 0.7


def test_checkpoint_blob_escape_survives_pymysql_122():
    import aiomysql.connection as connection

    from app.graph.checkpointer import _repair_aiomysql_blob_escape

    connection.escape_bytes_prefixed = "DO NOT IMPORT THIS!!!"
    _repair_aiomysql_blob_escape()
    rendered = connection.escape_bytes_prefixed(b"\x00\xff")
    assert rendered.startswith("_binary")
    assert "00ff" in rendered


def test_clean_query_drops_paths_addresses_and_line_numbers():
    query = clean_query(
        "AssertionError in tests/test_pricing.py:12 at 0xdeadbeef for flaky-shop",
        "pytest",
    )
    assert "/" not in query
    assert "\\" not in query
    assert "0x" not in query
    assert "pytest" in query
    assert len(query) <= 120


async def _seed(app, *, cancel: bool = False) -> Run:
    async with app.state.sessionmaker() as db:
        repo = await db.get(Repo, "flaky-shop")
        if repo is None:
            repo = Repo(
                id="flaky-shop", name="flaky-shop", description="", path="flaky-shop",
                test_count=0, editable_paths=["shop/**", "tests/**"],
            )
            db.add(repo)
        else:
            repo.editable_paths = ["shop/**", "tests/**"]
        run = Run(
            repo_id="flaky-shop", status="running", config={"time_budget_min": 25},
            steps=empty_steps(), cancel_requested=cancel,
        )
        db.add(run)
        await db.flush()
        flake = Flake(
            run_id=run.id, test_id="tests/test_pricing.py::test_convert",
            state="detected", fail_count=4, run_count=10, rate=0.4, ci_low=0.12, ci_high=0.74,
        )
        db.add(flake)
        await db.flush()
        db.add(Evidence(
            flake_id=flake.id,
            failing_samples=[{
                "outcome": "failed", "duration_ms": 20,
                "traceback": "AssertionError: assert 50.0 == 110.0",
                "order_window": ["tests/test_pricing.py::test_promo"],
            }],
            passing_samples=[],
        ))
        await db.commit()
        await db.refresh(run)
        return run


async def _counts(app, run_id: str) -> tuple[int, int, int]:
    async with app.state.sessionmaker() as db:
        flake_ids = select(Flake.id).where(Flake.run_id == run_id)
        diagnoses = int(await db.scalar(
            select(func.count()).select_from(Diagnosis).where(Diagnosis.flake_id.in_(flake_ids))
        ) or 0)
        references = int(await db.scalar(
            select(func.count()).select_from(Reference).where(Reference.flake_id.in_(flake_ids))
        ) or 0)
        calls = int(await db.scalar(
            select(func.count()).select_from(LlmCall).where(LlmCall.run_id == run_id)
        ) or 0)
        return diagnoses, references, calls


async def test_graph_stores_category_reference_and_diagnosis(app):
    run = await _seed(app)
    search = FakeSearch()
    await diagnose_flakes(
        app.state.sessionmaker, app.state.settings, run.id,
        search=search, checkpointer=MemorySaver(),
    )
    diagnoses, references, calls = await _counts(app, run.id)
    # classify, search, match, three diagnoses, three patches, expert summary
    assert (diagnoses, references, calls) == (1, 1, 10)
    assert search.calls == 1
    assert all("/" not in query for query in search.queries)
    async with app.state.sessionmaker() as db:
        flake = await db.scalar(select(Flake).where(Flake.run_id == run.id))
        diagnosis = await db.scalar(select(Diagnosis).where(Diagnosis.flake_id == flake.id))
        reference = await db.scalar(select(Reference).where(Reference.flake_id == flake.id))
        assert flake.category == "order_dependent"
        assert flake.state == "escalated"
        assert flake.routing == "escalate"
        assert flake.confidence_raw is not None
        assert flake.bisection is None
        rejected = list(await db.scalars(select(Patch).where(Patch.flake_id == flake.id)))
        assert len(rejected) == 3
        assert {row.status for row in rejected} == {"rejected"}
        assert any(
            item.get("rule") == "apply" for row in rejected for item in (row.violations or [])
        )
        assert diagnosis.agreement_k == 3 and diagnosis.agreement_n == 3
        assert reference.matched is True
        assert reference.snippet
        escalation = await db.scalar(select(Escalation).where(Escalation.flake_id == flake.id))
        assert escalation is not None and escalation.external_ref
        assert escalation.provider == "local"
        escalation_id = escalation.id
        state = {"run_id": run.id, "flake_id": flake.id, "test_id": flake.test_id}

    ctx = GraphContext(
        settings=app.state.settings, sessionmaker=app.state.sessionmaker,
        llm=Llm(app.state.settings, session_factory=app.state.sessionmaker), search=search,
    )
    token = current_context.set(ctx)
    try:
        await escalate(state)
        await classify(state)
        await research(state)
        await diagnose(state)
    finally:
        current_context.reset(token)
    again = await _counts(app, run.id)
    assert again == (1, 1, 10)
    assert search.calls == 1
    async with app.state.sessionmaker() as db:
        rows = list(await db.scalars(
            select(Escalation).where(Escalation.flake_id == state["flake_id"])
        ))
    assert len(rows) == 1
    assert rows[0].id == escalation_id


async def test_cancel_and_budget_skip_the_model(app):
    cancelled = await _seed(app, cancel=True)
    await diagnose_flakes(
        app.state.sessionmaker, app.state.settings, cancelled.id,
        search=FakeSearch(), checkpointer=MemorySaver(),
    )
    assert await _counts(app, cancelled.id) == (0, 0, 0)

    run = await _seed(app)
    async with app.state.sessionmaker() as db:
        db.add(LlmCall(
            run_id=run.id, node="prior", tier="reasoning", model="x", prompt_version="t",
            input_tokens=0, output_tokens=0, latency_ms=1, cost_usd=Decimal("2.00"), status="ok",
        ))
        await db.commit()
    await diagnose_flakes(
        app.state.sessionmaker, app.state.settings, run.id,
        search=FakeSearch(), checkpointer=MemorySaver(),
    )
    diagnoses, _references, calls = await _counts(app, run.id)
    assert diagnoses == 0
    assert calls == 1


async def test_search_outage_still_diagnoses(app):
    run = await _seed(app)
    await diagnose_flakes(
        app.state.sessionmaker, app.state.settings, run.id,
        search=FakeSearch(fail=True), checkpointer=MemorySaver(),
    )
    diagnoses, references, _calls = await _counts(app, run.id)
    assert diagnoses == 1
    assert references == 0


async def test_search_cache_reuses_a_query_for_a_day(app):
    search = FakeSearch()
    first, cached = await cached_search(app.state.sessionmaker, search, "pytest cache leak")
    second, again = await cached_search(app.state.sessionmaker, search, "pytest cache leak")
    assert search.calls == 1
    assert cached is False and again is True
    assert first == second
    async with app.state.sessionmaker() as db:
        row = await db.scalar(select(SearchCache).where(SearchCache.query == "pytest cache leak"))
    assert row is not None


async def test_environment_flake_is_not_patched(app):
    run = await _seed(app)
    async with app.state.sessionmaker() as db:
        flake = await db.scalar(select(Flake).where(Flake.run_id == run.id))
        flake.category = "environment"
        flake.state = "diagnosing"
        db.add(Diagnosis(
            flake_id=flake.id, attempt=1, root_cause="SHOP_CURRENCY is EUR",
            mechanism="The default comes from the environment.", culprit="shop/settings.py",
            category="environment", fix_strategy="A person changes the environment.",
            needs_human=True, self_confidence=0.9, agreement_k=3, agreement_n=3,
        ))
        await db.commit()
        flake_id = flake.id
        test_id = flake.test_id
        before = int(await db.scalar(
            select(func.count()).select_from(LlmCall).where(LlmCall.run_id == run.id)
        ) or 0)
    ctx = GraphContext(
        settings=app.state.settings, sessionmaker=app.state.sessionmaker,
        llm=Llm(app.state.settings, session_factory=app.state.sessionmaker), search=FakeSearch(),
    )
    token = current_context.set(ctx)
    try:
        await patch({"run_id": run.id, "flake_id": flake_id, "test_id": test_id})
    finally:
        current_context.reset(token)
    async with app.state.sessionmaker() as db:
        patches = int(await db.scalar(
            select(func.count()).select_from(Patch).where(Patch.flake_id == flake_id)
        ) or 0)
        after = int(await db.scalar(
            select(func.count()).select_from(LlmCall).where(LlmCall.run_id == run.id)
        ) or 0)
    assert patches == 0
    assert after == before


async def test_settled_patch_is_not_regenerated(app):
    run = await _seed(app)
    async with app.state.sessionmaker() as db:
        flake = await db.scalar(select(Flake).where(Flake.run_id == run.id))
        flake.category = "randomness"
        flake.state = "escalated"
        flake.routing = "escalate"
        db.add(Diagnosis(
            flake_id=flake.id, attempt=1, root_cause="codes collide",
            mechanism="The generator can repeat.", culprit="shop/coupons.py",
            category="randomness", fix_strategy="Use a set.",
            needs_human=False, self_confidence=0.9, agreement_k=2, agreement_n=3,
        ))
        db.add(Patch(
            flake_id=flake.id, attempt=1, diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n",
            summary="", status="verified", lines_changed=1,
        ))
        await db.commit()
        flake_id = flake.id
        test_id = flake.test_id
        before = int(await db.scalar(
            select(func.count()).select_from(LlmCall).where(LlmCall.run_id == run.id)
        ) or 0)
    ctx = GraphContext(
        settings=app.state.settings, sessionmaker=app.state.sessionmaker,
        llm=Llm(app.state.settings, session_factory=app.state.sessionmaker), search=FakeSearch(),
    )
    token = current_context.set(ctx)
    try:
        await patch({"run_id": run.id, "flake_id": flake_id, "test_id": test_id})
    finally:
        current_context.reset(token)
    async with app.state.sessionmaker() as db:
        patches = int(await db.scalar(
            select(func.count()).select_from(Patch).where(Patch.flake_id == flake_id)
        ) or 0)
        after = int(await db.scalar(
            select(func.count()).select_from(LlmCall).where(LlmCall.run_id == run.id)
        ) or 0)
        flake = await db.get(Flake, flake_id)
    assert patches == 1
    assert after == before
    assert flake.state == "escalated"
    assert flake.routing == "escalate"
