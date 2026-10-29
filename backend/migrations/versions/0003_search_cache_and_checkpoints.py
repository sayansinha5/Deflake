"""search cache and LangGraph checkpoint tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28 19:45:00
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_cache",
        sa.Column("query_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("fetched_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("query_hash"),
    )
    from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver

    from app.config import get_settings

    url = get_settings().migration_url(os.environ.get("MIGRATE_DB"))
    url = url.replace("mysql+pymysql://", "mysql://", 1)
    with PyMySQLSaver.from_conn_string(url) as saver:
        saver.setup()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS checkpoint_writes")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs")
    op.execute("DROP TABLE IF EXISTS checkpoints")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations")
    op.drop_table("search_cache")
