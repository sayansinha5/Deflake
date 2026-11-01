import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.api import (
    auth, calibration, escalations, flakes, github_oauth, health, members, notifications,
    repos, runs, usage, workspaces,
)
from app.api import settings as settings_api
from app.config import Settings, get_settings
from app.db.engine import build_engine, build_sessionmaker
from app.errors import install_error_handlers
from app.llm.factory import Llm
from app.logsetup import configure_logging
from app.middleware import CsrfHeaderMiddleware, RequestContextMiddleware
from app.preparer_client import PreparerClient
from app.runner_client import RunnerClient
from app.security.headers import SecurityHeadersMiddleware
from app.security.ratelimit import limiter
from app.services.escalation import POLL_SECONDS, poll_open
from app.services.run_manager import mark_interrupted

log = structlog.get_logger()


async def _poll_escalations(app: FastAPI) -> None:
    """Poll open escalations every five minutes. Never approves a task."""
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            await poll_open(app.state.sessionmaker, app.state.settings)
        except Exception:
            log.warning("escalation_poll_failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with app.state.sessionmaker() as session:
            await mark_interrupted(session)
            await session.commit()
        poller = asyncio.create_task(_poll_escalations(app))
        try:
            yield
        finally:
            poller.cancel()
            try:
                await poller
            except asyncio.CancelledError:
                pass
            await app.state.engine.dispose()

    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.engine = build_engine(settings)
    app.state.sessionmaker = build_sessionmaker(app.state.engine)
    app.state.limiter = limiter
    app.state.runner = RunnerClient(settings)
    app.state.preparer = PreparerClient(settings)
    app.state.llm = Llm(settings, session_factory=app.state.sessionmaker)

    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api")
    app.include_router(members.router, prefix="/api")
    app.include_router(workspaces.router, prefix="/api")
    app.include_router(notifications.router, prefix="/api")
    app.include_router(repos.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(flakes.router, prefix="/api")
    app.include_router(escalations.router, prefix="/api")
    app.include_router(calibration.router, prefix="/api")
    app.include_router(usage.router, prefix="/api")
    app.include_router(settings_api.router, prefix="/api")
    app.include_router(github_oauth.router, prefix="/api")

    # Added innermost first: the last middleware added runs first on each request.
    app.add_middleware(CsrfHeaderMiddleware)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With", "Last-Event-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
