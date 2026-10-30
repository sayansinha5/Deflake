"""repository sources and GitHub accounts

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30 04:40:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_accounts",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("user_id", sa.CHAR(length=36), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("connected_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_github_accounts_user_id"),
        sa.UniqueConstraint("github_user_id", name="uq_github_accounts_github_user_id"),
    )
    op.create_index("ix_github_accounts_user_id", "github_accounts", ["user_id"])

    op.add_column(
        "repos",
        sa.Column("source", sa.String(length=24), nullable=False, server_default="demo"),
    )
    op.add_column("repos", sa.Column("owner", sa.String(length=64), nullable=True))
    op.add_column("repos", sa.Column("default_branch", sa.String(length=255), nullable=True))
    op.add_column("repos", sa.Column("html_url", sa.String(length=512), nullable=True))
    op.add_column(
        "repos",
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("repos", sa.Column("github_account_id", sa.CHAR(length=36), nullable=True))
    op.add_column("repos", sa.Column("commit_sha", sa.String(length=64), nullable=True))
    op.add_column(
        "repos",
        sa.Column(
            "prepare_status", sa.String(length=24), nullable=False, server_default="ready",
        ),
    )
    op.add_column("repos", sa.Column("prepare_error", mysql.MEDIUMTEXT(), nullable=True))
    op.add_column("repos", sa.Column("last_prepared_at", mysql.DATETIME(fsp=6), nullable=True))
    op.add_column("repos", sa.Column("created_by", sa.CHAR(length=36), nullable=True))
    op.create_foreign_key(
        "fk_repos_github_account_id",
        "repos",
        "github_accounts",
        ["github_account_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_repos_created_by",
        "repos",
        "users",
        ["created_by"],
        ["id"],
    )
    op.create_index("ix_repos_source", "repos", ["source"])
    op.create_index("ix_repos_created_by", "repos", ["created_by"])
    op.create_index("ix_repos_prepare_status", "repos", ["prepare_status"])

    op.execute(
        "UPDATE repos SET source = 'demo', prepare_status = 'ready', "
        "is_private = 0 WHERE source IS NULL OR source = '' OR source = 'demo'"
    )


def downgrade() -> None:
    op.drop_index("ix_repos_prepare_status", table_name="repos")
    op.drop_index("ix_repos_created_by", table_name="repos")
    op.drop_index("ix_repos_source", table_name="repos")
    op.drop_constraint("fk_repos_created_by", "repos", type_="foreignkey")
    op.drop_constraint("fk_repos_github_account_id", "repos", type_="foreignkey")
    op.drop_column("repos", "created_by")
    op.drop_column("repos", "last_prepared_at")
    op.drop_column("repos", "prepare_error")
    op.drop_column("repos", "prepare_status")
    op.drop_column("repos", "commit_sha")
    op.drop_column("repos", "github_account_id")
    op.drop_column("repos", "is_private")
    op.drop_column("repos", "html_url")
    op.drop_column("repos", "default_branch")
    op.drop_column("repos", "owner")
    op.drop_column("repos", "source")
    op.drop_index("ix_github_accounts_user_id", table_name="github_accounts")
    op.drop_table("github_accounts")
