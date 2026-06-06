"""book_copies acquisition_date TIMESTAMPZ -> DATE

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-06 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "book_copies",
        "acquisition_date",
        type_=sa.Date(),
        postgresql_using="acquisition_date::date",
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "book_copies",
        "acquisition_date",
        type_=sa.DateTime(timezone=True),
        postgresql_using="acquisition_date::timestamp with time zone",
        existing_nullable=True,
    )
