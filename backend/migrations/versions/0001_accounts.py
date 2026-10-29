"""account tables: users, revoked_sessions, security_log

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("failed_attempts", sa.Integer, nullable=False),
        sa.Column("first_failed_at", DATETIME(fsp=6)),
        sa.Column("locked_until", DATETIME(fsp=6)),
        sa.Column("sessions_valid_after", DATETIME(fsp=6)),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("last_login_at", DATETIME(fsp=6)),
        **TABLE_OPTS,
    )
    op.create_table(
        "revoked_sessions",
        sa.Column("jti", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", DATETIME(fsp=6), nullable=False),
        **TABLE_OPTS,
    )
    op.create_table(
        "security_log",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_hash", sa.String(64)),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        **TABLE_OPTS,
    )
    op.create_index("ix_security_log_created_at", "security_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_security_log_created_at", table_name="security_log")
    op.drop_table("security_log")
    op.drop_table("revoked_sessions")
    op.drop_table("users")
