from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def build_engine(settings: Settings, url: str | None = None) -> AsyncEngine:
    engine = create_async_engine(
        url or settings.database_url,
        pool_size=settings.db_pool_size,
        pool_recycle=settings.db_pool_recycle_s,
        pool_pre_ping=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _session_defaults(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET time_zone = '+00:00'")
        cursor.execute(
            "SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
            "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
        )
        cursor.close()

    return engine


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with maker() as session:
        yield session
