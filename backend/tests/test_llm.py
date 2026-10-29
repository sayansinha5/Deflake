from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import LlmCall, Repo, Run
from app.llm.factory import Llm
from app.llm.routing import estimate_cost
from app.llm.usage import BudgetExceeded
from app.services.events import empty_steps


class SmokeOut(BaseModel):
    ok: bool
    one_word: str = ""
    tier: str = ""


async def _run(app) -> Run:
    async with app.state.sessionmaker() as db:
        if await db.get(Repo, "flaky-shop") is None:
            db.add(Repo(id="flaky-shop", name="flaky-shop", description="", path="flaky-shop",
                        test_count=0, editable_paths=[]))
        run = Run(repo_id="flaky-shop", status="running", config={}, steps=empty_steps())
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run


async def test_fake_structured_call_is_schema_valid(app):
    llm = Llm(app.state.settings, session_factory=app.state.sessionmaker)
    parsed = await llm.structured(
        SmokeOut, [{"role": "user", "content": "hello sk-abcdefghijklmnopqrstuvwxyz"}],
        tier="fast", node="smoke", prompt_version="t",
    )
    assert parsed.ok is True
    async with app.state.sessionmaker() as db:
        row = (await db.scalars(select(LlmCall).order_by(LlmCall.created_at.desc()))).first()
    assert row is not None and row.status == "ok" and row.model == "fake"


async def test_budget_stops_new_calls(app):
    run = await _run(app)
    async with app.state.sessionmaker() as db:
        db.add(LlmCall(
            run_id=run.id, node="prior", tier="reasoning", model="x", prompt_version="t",
            input_tokens=0, output_tokens=0, latency_ms=1, cost_usd=Decimal("2.00"),
            status="ok",
        ))
        await db.commit()
    llm = Llm(app.state.settings, session_factory=app.state.sessionmaker)
    try:
        await llm.structured(SmokeOut, [{"role": "user", "content": "x"}],
                             tier="fast", node="smoke", run_id=run.id)
        raise AssertionError("expected BudgetExceeded")
    except BudgetExceeded as exc:
        assert exc.code == "run_budget_reached"


def test_cost_estimate_from_prices(app):
    settings = app.state.settings.model_copy(update={
        "ai_price_fast_in_per_mtok": 0.06, "ai_price_fast_out_per_mtok": 0.24,
    })
    assert estimate_cost(settings, "fast", 1_000_000, 1_000_000) == 0.3
