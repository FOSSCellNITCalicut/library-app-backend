"""add users table

Revision ID: a7f3c2b1d9e0
Revises: ab6bfb6576f0
Create Date: 2026-06-16 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7f3c2b1d9e0'
down_revision: Union[str, Sequence[str], None] = 'ab6bfb6576f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('roll_no', sa.Text(), nullable=False),
        sa.Column('cgisessid', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        # Raw AES-GCM ciphertext. NULL when remember-me is not enabled.
        sa.Column('creds_enc', sa.LargeBinary(), nullable=True),
        # bcrypt hash of the refresh token -- never the raw token.
        sa.Column('refresh_token_hash', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('roll_no'),
    )


def downgrade() -> None:
    op.drop_table('users')
