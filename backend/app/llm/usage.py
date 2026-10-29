from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LlmCall, Run
from app.errors import ApiError
from app.llm.routing import estimate_cost


class BudgetExceeded(ApiError):
    def __init__(self) -> None:
        super().__init__(
            409, "run_budget_reached",
            "This scan reached its model-spend cap. Remaining work was stopped.",
        )


async def spent_usd(session: AsyncSession, run_id: str) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(LlmCall.run_id == run_id)
    )
    return Decimal(total or 0)


async def assert_budget(session: AsyncSession, run_id: str, cap: float) -> None:
    if await spent_usd(session, run_id) >= Decimal(str(cap)):
        raise BudgetExceeded()


async def record_call(
    session: AsyncSession,
    *,
    run_id: str | None,
    flake_id: str | None,
    node: str,
    tier: str,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    status: str,
    error_type: str | None,
    settings,
) -> LlmCall:
    cost = estimate_cost(settings, tier, input_tokens, output_tokens)  # type: ignore[arg-type]
    row = LlmCall(
        run_id=run_id, flake_id=flake_id, node=node, tier=tier, model=model,
        prompt_version=prompt_version, input_tokens=input_tokens, output_tokens=output_tokens,
        latency_ms=latency_ms, cost_usd=Decimal(str(cost)), status=status, error_type=error_type,
    )
    session.add(row)
    if run_id is not None:
        await session.execute(
            update(Run).where(Run.id == run_id).values(
                cost_usd=func.coalesce(Run.cost_usd, 0) + Decimal(str(cost))
            )
        )
    await session.flush()
    return row
