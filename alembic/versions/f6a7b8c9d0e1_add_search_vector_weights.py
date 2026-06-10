"""add search vector weights (title=A, author=B, subject=C, description=D)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old trigger and function
    op.execute("DROP TRIGGER IF EXISTS books_search_vector_trigger ON books;")
    op.execute("DROP FUNCTION IF EXISTS books_search_vector_update();")

    # Recreate with setweight
    op.execute("""
        CREATE FUNCTION books_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(array_to_string(NEW.authors, ' '), '')), 'B') ||
                setweight(to_tsvector('english', coalesce(array_to_string(NEW.categories, ' '), '')), 'C') ||
                setweight(to_tsvector('english', coalesce(NEW.description, '')), 'D');
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

    # Re-populate existing rows
    op.execute("""
        UPDATE books
        SET search_vector =
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(array_to_string(authors, ' '), '')), 'B') ||
            setweight(to_tsvector('english', coalesce(array_to_string(categories, ' '), '')), 'C') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'D');
    """)


def downgrade() -> None:
    # Drop weighted trigger and function
    op.execute("DROP TRIGGER IF EXISTS books_search_vector_trigger ON books;")
    op.execute("DROP FUNCTION IF EXISTS books_search_vector_update();")

    # Restore original unweighted function from the previous migration
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

    # Re-populate with unweighted
    op.execute("""
        UPDATE books
        SET search_vector =
            to_tsvector(
                'english',
                coalesce(title,'') || ' ' ||
                coalesce(array_to_string(authors,' '),'') || ' ' ||
                coalesce(array_to_string(categories,' '),'') || ' ' ||
                coalesce(description,'')
            );
    """)
