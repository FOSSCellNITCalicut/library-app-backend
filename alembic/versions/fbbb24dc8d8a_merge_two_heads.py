"""merge two heads

Revision ID: fbbb24dc8d8a
Revises: a7f3c2b1d9e0, f6a7b8c9d0e1
Create Date: 2026-06-16 19:25:26.068200

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fbbb24dc8d8a'
down_revision: Union[str, Sequence[str], None] = ('a7f3c2b1d9e0', 'f6a7b8c9d0e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
