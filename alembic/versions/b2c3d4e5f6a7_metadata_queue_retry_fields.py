"""metadata_queue retry fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-05 21:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS metadata_queue")

    op.create_table(
        "metadata_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("biblio_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "available_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("metadata_queue")
