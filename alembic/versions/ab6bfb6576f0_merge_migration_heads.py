"""merge migration heads

Revision ID: ab6bfb6576f0
Revises: 0fe4da6af43e, d4e5f6a7b8c9
Create Date: 2026-06-06 18:23:25.103238

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'ab6bfb6576f0'
down_revision: Union[str, Sequence[str], None] = ('0fe4da6af43e', 'd4e5f6a7b8c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Empty migration file needed to merge the two heads (0fe4da6af43e and d4e5f6a7b8c9) into a single head (ab6bfb6576f0)

def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
