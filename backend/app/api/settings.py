"""Non-secret workspace settings and a local connection check."""
import time

import httpx
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentSession, current_session, get_db, get_settings_dep
from app.config import Settings
from app.errors import ApiError
from app.schemas.settings import DefaultsUpdateIn
from app.services import github_accounts
from app.services import workspace_defaults as defaults_service

router = APIRouter(prefix="/settings", tags=["settings"])
NAMES = {"ai", "tavily", "tendem", "toloka", "runner", "preparer"}


def _state(configured: bool, enabled: bool = True) -> str:
    if not enabled:
        return "disabled"
    return "configured" if configured else "missing"


def _view(
    settings: Settings,
    github_connection: dict | None = None,
    *,
    detect_reruns: int | None = None,
    verify_reruns: int | None = None,
) -> dict:
    provider = settings.ai_provider
    ai_label = "Token Factory" if provider == "nebius_token_factory" else "Model provider"
    toloka_on = settings.audit_provider == "toloka"
    github = {
        "import_enabled": getattr(settings, "github_import_enabled", True),
        "oauth_enabled": getattr(settings, "github_oauth_enabled", False),
        "connected": False,
    }
    if github_connection:
        github.update(github_connection)
    return {
        "ai_provider": provider,
        "using_token_factory": provider == "nebius_token_factory",
        "models": {
            "fast": settings.ai_model_fast,
            "balanced": settings.ai_model_balanced,
            "reasoning": settings.ai_model_reasoning,
        },
        "defaults": {
            "detect_reruns": settings.detect_reruns if detect_reruns is None else detect_reruns,
            "verify_reruns": settings.verify_reruns if verify_reruns is None else verify_reruns,
            "confidence_threshold": settings.confidence_threshold_default,
            "run_budget_usd": settings.ai_run_budget_usd,
            "escalation_provider": settings.escalation_provider,
            "escalation_fallback": settings.escalation_fallback,
            "detect_choices": list(defaults_service.DETECT_CHOICES),
            "verify_choices": list(defaults_service.VERIFY_CHOICES),
        },
        "github": github,
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
            {
                "id": "preparer",
                "label": "Preparer",
                "status": _state(True, getattr(settings, "github_import_enabled", True)),
                "detail": None,
            },
        ],
    }


@router.get("")
async def get_settings_view(
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    account = await github_accounts.get_active_account(db, session.user.id)
    stored = await defaults_service.get_defaults(db, settings)
    return _view(
        settings,
        github_accounts.connection_public_view(account),
        detect_reruns=stored["detect_reruns"],
        verify_reruns=stored["verify_reruns"],
    )


@router.put("/defaults")
async def update_defaults(
    body: DefaultsUpdateIn,
    session: CurrentSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    stored = await defaults_service.put_defaults(
        db,
        settings,
        session.user.id,
        detect_reruns=body.detect_reruns,
        verify_reruns=body.verify_reruns,
    )
    account = await github_accounts.get_active_account(db, session.user.id)
    return _view(
        settings,
        github_accounts.connection_public_view(account),
        detect_reruns=stored["detect_reruns"],
        verify_reruns=stored["verify_reruns"],
    )


@router.post("/test/{name}")
async def test_integration(
    name: str = Path(pattern="^(ai|tavily|tendem|toloka|runner|preparer)$"),
    _user: CurrentSession = Depends(current_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    if name not in NAMES:
        raise ApiError(404, "not_found", "Unknown integration.")
    started = time.perf_counter()
    if name in {"runner", "preparer"}:
        url = settings.runner_url if name == "runner" else settings.preparer_url
        label = "Runner" if name == "runner" else "Preparer"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{url}/healthz")
            ok = response.status_code == 200
            message = f"{label} responded." if ok else f"{label} did not respond."
        except httpx.HTTPError:
            ok = False
            message = f"{label} did not respond."
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
