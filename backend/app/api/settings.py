"""Non-secret workspace settings and a local connection check."""
import time

import httpx
from fastapi import APIRouter, Depends, Path

from app.api.deps import CurrentSession, current_session, get_settings_dep
from app.config import Settings
from app.errors import ApiError

router = APIRouter(prefix="/settings", tags=["settings"])
NAMES = {"ai", "tavily", "tendem", "toloka", "runner"}


def _state(configured: bool, enabled: bool = True) -> str:
    if not enabled:
        return "disabled"
    return "configured" if configured else "missing"


def _view(settings: Settings) -> dict:
    provider = settings.ai_provider
    ai_label = "Token Factory" if provider == "nebius_token_factory" else "Model provider"
    toloka_on = settings.audit_provider == "toloka"
    return {
        "ai_provider": provider,
        "using_token_factory": provider == "nebius_token_factory",
        "models": {
            "fast": settings.ai_model_fast,
            "balanced": settings.ai_model_balanced,
            "reasoning": settings.ai_model_reasoning,
        },
        "defaults": {
            "detect_reruns": settings.detect_reruns,
            "verify_reruns": settings.verify_reruns,
            "confidence_threshold": settings.confidence_threshold_default,
            "run_budget_usd": settings.ai_run_budget_usd,
            "escalation_provider": settings.escalation_provider,
            "escalation_fallback": settings.escalation_fallback,
        },
        "integrations": [
            {
                "id": "ai",
                "label": ai_label,
                "status": _state(settings.ai_api_key is not None, provider != "fake"),
                "detail": provider,
            },
            {
                "id": "tavily",
                "label": "Tavily",
                "status": _state(settings.tavily_api_key is not None, settings.tavily_enabled),
                "detail": None,
            },
            {
                "id": "tendem",
                "label": "Tendem",
                "status": _state(settings.tendem_api_key is not None),
                "detail": settings.escalation_fallback,
            },
            {
                "id": "toloka",
                "label": "Toloka",
                "status": _state(settings.toloka_api_key is not None, toloka_on),
                "detail": settings.audit_provider,
            },
            {
                "id": "runner",
                "label": "Runner",
                "status": "configured",
                "detail": None,
            },
        ],
    }


@router.get("")
async def get_settings_view(
    _user: CurrentSession = Depends(current_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    return _view(settings)


@router.post("/test/{name}")
async def test_integration(
    name: str = Path(pattern="^(ai|tavily|tendem|toloka|runner)$"),
    _user: CurrentSession = Depends(current_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    if name not in NAMES:
        raise ApiError(404, "not_found", "Unknown integration.")
    started = time.perf_counter()
    if name == "runner":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{settings.runner_url}/healthz")
            ok = response.status_code == 200
            message = "Runner responded." if ok else "Runner did not respond."
        except httpx.HTTPError:
            ok = False
            message = "Runner did not respond."
    else:
        row = next(item for item in _view(settings)["integrations"] if item["id"] == name)
        ok = row["status"] == "configured"
        message = {
            "configured": "The key is set. This check does not call the service.",
            "missing": "No key is set.",
            "disabled": "This integration is turned off.",
        }[row["status"]]
    elapsed = int((time.perf_counter() - started) * 1000)
    return {"ok": ok, "latency_ms": elapsed, "message": message}
