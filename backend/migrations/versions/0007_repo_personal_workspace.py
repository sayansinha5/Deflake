"""repo personal flag and workspace_id

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01 14:40:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repos",
        sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("repos", sa.Column("workspace_id", sa.CHAR(length=36), nullable=True))
    op.create_foreign_key(
        "fk_repos_workspace_id",
        "repos",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    op.create_index("ix_repos_workspace_id", "repos", ["workspace_id"])
    op.create_index("ix_repos_is_personal", "repos", ["is_personal"])
    # Demo stays shared; existing imports become personal to their importer.
    op.execute("UPDATE repos SET is_personal = 0, workspace_id = NULL WHERE source = 'demo'")
    op.execute(
        "UPDATE repos SET is_personal = 1 WHERE source <> 'demo'"
    )


def downgrade() -> None:
    op.drop_index("ix_repos_is_personal", table_name="repos")
    op.drop_index("ix_repos_workspace_id", table_name="repos")
    op.drop_constraint("fk_repos_workspace_id", "repos", type_="foreignkey")
    op.drop_column("repos", "workspace_id")
    op.drop_column("repos", "is_personal")
