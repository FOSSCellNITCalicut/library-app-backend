"""fix MARC author name format (Last, First -> First Last)

Revision ID: 2e3f4a5b6c7d
Revises: d94a1b2c3e4f
Create Date: 2026-06-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2e3f4a5b6c7d'
down_revision: Union[str, Sequence[str], None] = 'd94a1b2c3e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE books
        SET authors = (
            SELECT array_agg(
                regexp_replace(
                    regexp_replace(author, '^([^,]+),\\s*(.*)$', '\\2 \\1'),
                    ',', '', 'g'
                )
                ORDER BY ordinality
            )
            FROM unnest(authors) WITH ORDINALITY AS arr(author, ordinality)
        )
        WHERE authors IS NOT NULL;
    """)


def downgrade() -> None:
    # This transformation is lossy and cannot be automatically reversed
    # (e.g., "S. Natarajan" could be from "Natarajan, S." or original "S. Natarajan").
    # If you need the old format, re-sync from Koha.
    pass
