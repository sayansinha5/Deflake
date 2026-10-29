import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.db.models import Base

target_metadata = Base.metadata


def _url() -> str:
    db_name = context.get_x_argument(as_dictionary=True).get("db") or os.environ.get("MIGRATE_DB")
    return get_settings().migration_url(db_name)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
