"""add external_id to book_copies

Revision ID: 865bf0604c97
Revises: 2a0fe573f25e
Create Date: 2026-08-08 23:58:07.377611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '865bf0604c97'
down_revision: Union[str, Sequence[str], None] = '2a0fe573f25e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('book_copies', sa.Column('external_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('book_copies', 'external_id')
