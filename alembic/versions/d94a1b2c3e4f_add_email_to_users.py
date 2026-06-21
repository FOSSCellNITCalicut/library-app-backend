"""add email column to users

Revision ID: d94a1b2c3e4f
Revises: d15761081368
Create Date: 2026-06-19 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd94a1b2c3e4f'
down_revision: Union[str, Sequence[str], None] = 'd15761081368'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'email')
