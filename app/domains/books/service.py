from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.db.models.book import Book
from app.domains.books.schemas import SearchResponse, BookCard, BrowseResponse, BookDetail

PAGE_SIZE = 50

#BROWSE
async def get_browse_books(db: AsyncSession, page:int) -> BrowseResponse:
    offset=(page-1)*PAGE_SIZE;

    result=await db.execute(

            select(Book)
            .order_by(Book.created_at.desc())
            .offset(offset)
            .limit(PAGE_SIZE + 1)

    )
    books=result.scalars().all()

    has_more=len(books)>PAGE_SIZE
    books=books[:PAGE_SIZE]

    return BrowseResponse(
        items=[_to_card(b) for b in books],
        page=page,
        page_size=PAGE_SIZE,
        has_more=has_more
    )


#Seearch

async def search_books(db: AsyncSession, q: str) -> SearchResponse:
    tsquery = func.plainto_tsquery("english", q)

    # Full-text search
    result = await db.execute(
        select(Book)
        .where(Book.search_vector.op("@@")(tsquery))
        .limit(PAGE_SIZE)
    )
    books = result.scalars().all()

    # Fallback search if no FTS results
    if not books:
        result = await db.execute(
            select(Book)
            .where(
                or_(
                    Book.title.ilike(f"%{q}%"),
                    func.array_to_string(Book.authors, " ").ilike(f"%{q}%"),
                )
            )
            .limit(PAGE_SIZE)
        )
        books = result.scalars().all()

    
    return SearchResponse(
        items=[_to_card(b) for b in books],
        query=q,
        total=len(books),
    )


# book detail

async def get_book_by_id(db: AsyncSession, biblio_id: int ) -> BookDetail | None:
    result = await db.execute(
        select(Book).where(Book.biblio_id == biblio_id)
    
    )
    book=result.scalars().one_or_none()

    if book is None:
        return None
    
    return BookDetail(
        biblio_id=book.biblio_id,
        title=book.title,
        authors=book.authors or [],
        isbn=book.isbn or [],
        publisher=book.publisher,
        published_year=book.published_year,
        edition=book.edition,
        description=book.description,
        cover_url=book.cover_url,
        categories=book.categories or [],
        available_copies=book.available_copies,
        total_copies=book.total_copies,
        lib_copies=book.lib_copies,
        mat_copies=book.mat_copies,
    )

#helper



def _to_card(book: Book) -> BookCard:
    return BookCard(
        biblio_id=book.biblio_id,
        title=book.title,
        authors=book.authors or [],
        isbn=book.isbn or [],   
        cover_url=book.cover_url,
    )
