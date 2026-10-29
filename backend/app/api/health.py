import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    checks: dict[str, str] = {"config": "ok"}

    try:
        async with request.app.state.sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unreachable"

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.runner_url}/healthz")
        checks["runner"] = "ok" if r.status_code == 200 else "unhealthy"
    except httpx.HTTPError:
        checks["runner"] = "unreachable"

    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )
