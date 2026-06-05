"""default number of copies 0

Revision ID: 0fe4da6af43e
Revises: 8cb19fefb0b7
Create Date: 2026-06-05 12:29:37.294924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0fe4da6af43e'
down_revision: Union[str, Sequence[str], None] = '8cb19fefb0b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # drop trigger and function that reference the old column name
    op.execute("DROP TRIGGER IF EXISTS books_search_vector_trigger ON books;")
    op.execute("DROP FUNCTION IF EXISTS books_search_vector_update();")

    op.alter_column('books', 'author', new_column_name='authors')

    op.alter_column('books', 'total_copies', server_default='0')
    op.alter_column('books', 'available_copies', server_default='0')
    op.alter_column('books', 'lib_copies', server_default='0')
    op.alter_column('books', 'mat_copies', server_default='0')

    # recreate trigger function with new column name
    op.execute("""
        CREATE FUNCTION books_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector(
                'english',
                coalesce(NEW.title,'') || ' ' ||
                coalesce(array_to_string(NEW.authors,' '),'') || ' ' ||
                coalesce(array_to_string(NEW.categories,' '),'') || ' ' ||
                coalesce(NEW.description,'')
            );
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER books_search_vector_trigger
        BEFORE INSERT OR UPDATE
        ON books
        FOR EACH ROW
        EXECUTE FUNCTION books_search_vector_update();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS books_search_vector_trigger ON books;")
    op.execute("DROP FUNCTION IF EXISTS books_search_vector_update();")

    op.alter_column('books', 'authors', new_column_name='author')

    op.alter_column('books', 'total_copies', server_default=None)
    op.alter_column('books', 'available_copies', server_default=None)
    op.alter_column('books', 'lib_copies', server_default=None)
    op.alter_column('books', 'mat_copies', server_default=None)

    op.execute("""
        CREATE FUNCTION books_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector(
                'english',
                coalesce(NEW.title,'') || ' ' ||
                coalesce(array_to_string(NEW.author,' '),'') || ' ' ||
                coalesce(array_to_string(NEW.categories,' '),'') || ' ' ||
                coalesce(NEW.description,'')
            );
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER books_search_vector_trigger
        BEFORE INSERT OR UPDATE
        ON books
        FOR EACH ROW
        EXECUTE FUNCTION books_search_vector_update();
    """)
