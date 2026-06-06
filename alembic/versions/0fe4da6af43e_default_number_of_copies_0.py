"""default number of copies 0

Revision ID: 0fe4da6af43e
Revises: 8cb19fefb0b7
Create Date: 2026-06-05 12:29:37.294924

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0fe4da6af43e'
down_revision: Union[str, Sequence[str], None] = '8cb19fefb0b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('books', 'total_copies', server_default='0')
    op.alter_column('books', 'available_copies', server_default='0')
    op.alter_column('books', 'lib_copies', server_default='0')
    op.alter_column('books', 'mat_copies', server_default='0')


def downgrade() -> None:
    op.alter_column('books', 'total_copies', server_default=None)
    op.alter_column('books', 'available_copies', server_default=None)
    op.alter_column('books', 'lib_copies', server_default=None)
    op.alter_column('books', 'mat_copies', server_default=None)
