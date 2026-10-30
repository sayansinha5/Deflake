"""workspace defaults for scan detect and verify reruns

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30 16:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_defaults",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("detect_reruns", sa.Integer(), nullable=False),
        sa.Column("verify_reruns", sa.Integer(), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_by", sa.CHAR(length=36), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("workspace_defaults")
