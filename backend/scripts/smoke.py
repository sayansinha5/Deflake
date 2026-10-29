"""One structured call per model tier. Prints model, tokens, latency and estimated cost.

    docker compose -f backend/docker-compose.yml exec api python scripts/smoke.py
"""
import asyncio
import sys
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.engine import build_engine, build_sessionmaker  # noqa: E402
from app.llm.factory import Llm  # noqa: E402
from app.llm.routing import model_id  # noqa: E402
from app.llm.usage import estimate_cost  # noqa: E402


class SmokeOut(BaseModel):
    ok: bool
    one_word: str = Field(max_length=32)


async def main() -> int:
    settings = get_settings()
    engine = build_engine(settings)
    maker = build_sessionmaker(engine)
    llm = Llm(settings, session_factory=maker)
    print(f"provider={settings.ai_provider}  method={settings.ai_structured_output_method}")
    try:
        for tier in ("fast", "balanced", "reasoning"):
            name = "fake" if settings.ai_provider == "fake" else model_id(settings, tier)
            parsed = await llm.structured(
                SmokeOut,
                [
                    {"role": "system", "content": "Return JSON only. No secrets."},
                    {"role": "user", "content": "Set ok to true and one_word to pong."},
                ],
                tier=tier,  # type: ignore[arg-type]
                node="smoke",
                prompt_version="smoke-1",
            )
            async with maker() as session:
                from sqlalchemy import select

                from app.db.models import LlmCall

                row = (await session.scalars(
                    select(LlmCall).order_by(LlmCall.created_at.desc()).limit(1)
                )).first()
            cost = estimate_cost(
                settings, tier, row.input_tokens if row else 0, row.output_tokens if row else 0  # type: ignore[arg-type]
            )
            print(
                f"{tier:10} model={name}  parsed={parsed.model_dump()}  "
                f"tokens_in={row.input_tokens if row else 0}  "
                f"tokens_out={row.output_tokens if row else 0}  "
                f"latency_ms={row.latency_ms if row else 0}  "
                f"cost_usd~{cost:.6f}  status={row.status if row else '?'}"
            )
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
