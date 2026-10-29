import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.engine import build_engine
from app.db.models import User
from app.main import create_app
from app.security.passwords import hash_password
from app.security.ratelimit import limiter, signin_failures

BACKEND_DIR = Path(__file__).resolve().parents[1]
CSRF = {"X-Requested-With": "deflake"}
OWNER_EMAIL = "owner@example.test"
OWNER_PASSWORD = "Owner-test-pass-2026"
MEMBER_EMAIL = "member@example.test"
MEMBER_PASSWORD = "Member-test-pass-2026"


def make_settings(**overrides) -> Settings:
    base_db = os.environ.get("DB_NAME", "deflake")
    values = {
        "app_env": "development",
        "ai_provider": "fake",
        "db_name": f"{base_db}_test",
        "signup_enabled": True,
        "cors_allowed_origins": "http://localhost:5173",
        "log_level": "WARNING",
        "tendem_api_key": None,
        "github_token": None,
        "github_repo": None,
        "escalation_provider": "tendem",
        "escalation_fallback": "local",
        "toloka_api_key": None,
        "audit_provider": "csv_import",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(scope="session")
def migrated_test_db() -> str:
    settings = make_settings()
    os.environ["MIGRATE_DB"] = settings.db_name
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")
    return settings.db_name


@pytest.fixture
async def app_factory(migrated_test_db):
    """Yields a function that builds an app whose DB work is rolled back after the test."""
    engines = []
    connections = []

    async def factory(**overrides):
        settings = make_settings(**overrides)
        app = create_app(settings)
        engine = build_engine(settings)
        conn = await engine.connect()
        await conn.begin()
        app.state.sessionmaker = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        engines.extend([engine, app.state.engine])
        connections.append(conn)
        return app

    limiter.reset()
    signin_failures.reset()
    yield factory
    for conn in connections:
        await conn.rollback()
        await conn.close()
    for engine in engines:
        await engine.dispose()


@pytest.fixture
async def app(app_factory):
    return await app_factory()


def client_for(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
async def client(app):
    async with client_for(app) as c:
        yield c


async def add_user(app, email: str, password: str, role: str = "member") -> User:
    async with app.state.sessionmaker() as db:
        user = User(email=email, full_name=email.split("@")[0].title(),
                    password_hash=hash_password(password), role=role)
        db.add(user)
        await db.commit()
        return user


async def sign_in(client: AsyncClient, email: str, password: str):
    return await client.post("/api/auth/session", json={"email": email, "password": password},
                             headers=CSRF)
