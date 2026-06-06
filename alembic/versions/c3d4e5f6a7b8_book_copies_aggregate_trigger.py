"""book_copies aggregate trigger

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-05 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TRIGGER_FUNCTION_DDL = """
CREATE OR REPLACE FUNCTION recompute_book_aggregates() RETURNS TRIGGER AS $$
DECLARE
    affected_biblio_id BIGINT;
BEGIN
    affected_biblio_id := COALESCE(NEW.biblio_id, OLD.biblio_id);

    UPDATE books SET
        total_copies = agg.total,
        available_copies = agg.available,
        lib_copies = agg.lib,
        mat_copies = agg.mat,
        availability_synced_at = NOW()
    FROM (
        SELECT
            COUNT(*)::INT AS total,
            COUNT(*) FILTER (WHERE status = 'Available')::INT AS available,
            COUNT(*) FILTER (WHERE branch = 'LIB')::INT AS lib,
            COUNT(*) FILTER (WHERE branch = 'MAT')::INT AS mat
        FROM book_copies
        WHERE biblio_id = affected_biblio_id
    ) AS agg
    WHERE books.biblio_id = affected_biblio_id;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


TRIGGER_DDL = """
CREATE TRIGGER book_copies_aggregates
AFTER INSERT OR UPDATE OR DELETE ON book_copies
FOR EACH ROW EXECUTE FUNCTION recompute_book_aggregates();
"""


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS book_copies_aggregates ON book_copies;")
    op.execute("DROP FUNCTION IF EXISTS recompute_book_aggregates();")
    op.execute(TRIGGER_FUNCTION_DDL)
    op.execute(TRIGGER_DDL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS book_copies_aggregates ON book_copies;")
    op.execute("DROP FUNCTION IF EXISTS recompute_book_aggregates();")
