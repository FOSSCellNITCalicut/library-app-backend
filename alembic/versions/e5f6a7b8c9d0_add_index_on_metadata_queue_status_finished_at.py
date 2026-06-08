"""add index on metadata_queue (status, finished_at)

Revision ID: e5f6a7b8c9d0
Revises: 2ca996f4895c
Create Date: 2026-06-08 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "2ca996f4895c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_metadata_queue_status_finished_at",
        "metadata_queue",
        ["status", "finished_at"],
        postgresql_where=None,
    )


def downgrade() -> None:
    op.drop_index("ix_metadata_queue_status_finished_at", table_name="metadata_queue")
