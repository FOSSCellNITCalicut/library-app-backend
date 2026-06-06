"""sync_state singleton

Revision ID: a1b2c3d4e5f6
Revises: 44c271c1bb6d
Create Date: 2026-06-05 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "44c271c1bb6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sync_state")

    op.create_table(
        "sync_state",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            server_default="1",
        ),
        sa.Column(
            "current_page",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        "INSERT INTO sync_state (id, current_page) VALUES (1, 1)"
    )


def downgrade() -> None:
    op.drop_table("sync_state")
