from typing import Literal

Tier = Literal["fast", "balanced", "reasoning"]

TIER_TO_SETTING = {
    "fast": "ai_model_fast",
    "balanced": "ai_model_balanced",
    "reasoning": "ai_model_reasoning",
}

TIER_TO_PRICE = {
    "fast": ("ai_price_fast_in_per_mtok", "ai_price_fast_out_per_mtok"),
    "balanced": ("ai_price_balanced_in_per_mtok", "ai_price_balanced_out_per_mtok"),
    "reasoning": ("ai_price_reasoning_in_per_mtok", "ai_price_reasoning_out_per_mtok"),
}

TASK_TIER: dict[str, Tier] = {
    "classify": "fast",
    "search_query": "fast",
    "summarize": "fast",
    "diagnose": "reasoning",
    "patch": "balanced",
    "repair_patch": "balanced",
    "escalation_summary": "balanced",
}


def model_id(settings, tier: Tier) -> str:
    value = getattr(settings, TIER_TO_SETTING[tier])
    if not value:
        raise RuntimeError(f"No model ID configured for tier {tier}.")
    return value


def prices(settings, tier: Tier) -> tuple[float | None, float | None]:
    inn, out = TIER_TO_PRICE[tier]
    return getattr(settings, inn), getattr(settings, out)


def estimate_cost(settings, tier: Tier, input_tokens: int, output_tokens: int) -> float:
    inn, out = prices(settings, tier)
    total = 0.0
    if inn is not None:
        total += (input_tokens / 1_000_000) * inn
    if out is not None:
        total += (output_tokens / 1_000_000) * out
    return round(total, 6)
