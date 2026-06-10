# AI-generated test cases — verify behaviour, not implementation details.

import pytest

from app.domains.books.service import BookNotFoundError, BookService, ValidationError


class FakeRepository:
    def __init__(self):
        self.books = [
            {
                "biblio_id": 1,
                "title": "The Great Gatsby",
                "authors": ["F. Scott Fitzgerald"],
                "publisher": "Scribner",
                "published_year": 1925,
                "isbn": "9780743273565",
                "categories": ["Fiction", "Classic"],
                "description": "A story of the mysteriously wealthy Jay Gatsby.",
                "score": 9.0,
            },
            {
                "biblio_id": 2,
                "title": "To Kill a Mockingbird",
                "authors": ["Harper Lee"],
                "publisher": "J.B. Lippincott & Co.",
                "published_year": 1960,
                "isbn": "9780061120084",
                "categories": ["Fiction", "Drama"],
                "description": "A novel about racial injustice.",
                "score": 8.5,
            },
            {
                "biblio_id": 3,
                "title": "1984",
                "authors": ["George Orwell"],
                "publisher": "Secker & Warburg",
                "published_year": 1949,
                "isbn": "9780451524935",
                "categories": ["Dystopian", "Science Fiction"],
                "description": "A dystopian social science fiction novel.",
                "score": 7.0,
            },
            {
                "biblio_id": 4,
                "title": "Pride and Prejudice",
                "authors": ["Jane Austen"],
                "publisher": "T. Egerton",
                "published_year": 1813,
                "isbn": "9780141439518",
                "categories": ["Romance", "Classic"],
                "description": "A romantic novel of manners.",
                "score": None,
            },
            {
                "biblio_id": 5,
                "title": "The Catcher in the Rye",
                "authors": ["J.D. Salinger"],
                "publisher": "Little, Brown and Company",
                "published_year": 1951,
                "isbn": "9780316769488",
                "categories": ["Fiction", "Coming-of-age"],
                "description": "A story about teenage angst.",
                "score": None,
            },
        ]
        self.copies = {
            1: [
                {"branch": "Main Library", "status": "available", "call_number": "813.52 FIT"},
                {"branch": "Science Branch", "status": "checked_out", "call_number": "813.52 FIT"},
            ],
            2: [
                {"branch": "Main Library", "status": "available", "call_number": "813.54 LEE"},
            ],
        }
        self._call_count = 0

    async def search_by_isbn(self, isbn):
        results = [
            dict(b) for b in self.books
            if b["isbn"] == isbn
        ]
        return results

    async def search_books(self, query, offset=None, limit=None):
        self._call_count += 1
        q = query.lower()
        results = [
            b for b in self.books
            if q in b["title"].lower()
            or any(q in a.lower() for a in b.get("authors", []))
            or any(q in c.lower() for c in b["categories"])
        ]
        total = len(results)
        if offset is not None and limit is not None:
            results = results[offset:offset + limit]
        return results, total

    async def browse_books(self, offset=0, limit=20, sort_by="title", sort_order="asc"):
        self._call_count += 1
        results = list(self.books)
        sort_key = {"title": "title", "published_year": "published_year", "author": "authors", "publisher": "publisher"}.get(sort_by, "title")
        reverse = sort_order == "desc"

        def sort_val(book):
            val = book.get(sort_key)
            if val is None:
                return (1, "") if sort_order == "asc" else (0, "")
            if isinstance(val, list):
                val = val[0] if val else ""
            return (0, val) if isinstance(val, str) else (0, val)

        results.sort(key=sort_val, reverse=reverse)
        total = len(results)
        paged = results[offset:offset + limit]
        return paged, total

    async def get_book_by_id(self, biblio_id):
        self._call_count += 1
        for b in self.books:
            if b["biblio_id"] == biblio_id:
                return dict(b)
        return None

    async def get_book_copies(self, biblio_id):
        return self.copies.get(biblio_id, [])


@pytest.fixture
def service():
    return BookService(FakeRepository())


@pytest.mark.asyncio
class TestSearchByISBN:
    async def test_search_by_isbn_found(self, service):
        result = await service.search_by_isbn("9780743273565")
        assert isinstance(result, dict)
        assert len(result["items"]) == 1
        assert result["items"][0]["title"] == "The Great Gatsby"
        assert result["total"] == 1

    async def test_search_by_isbn_not_found(self, service):
        result = await service.search_by_isbn("0000000000000")
        assert len(result["items"]) == 0
        assert result["total"] == 0

    async def test_search_by_isbn_empty_raises(self, service):
        with pytest.raises(ValidationError, match="ISBN must not be empty"):
            await service.search_by_isbn("")

    async def test_search_by_isbn_returns_flat(self, service):
        result = await service.search_by_isbn("9780743273565")
        assert "items" in result
        assert "page" in result
        assert "per_page" in result
        assert "total" in result
        assert result["page"] == 1


@pytest.mark.asyncio
class TestSearchBooks:
    async def test_basic_search(self, service):
        result = await service.search_books(query="Gatsby")
        assert isinstance(result, dict)
        assert len(result["items"]) == 1
        assert result["items"][0]["title"] == "The Great Gatsby"

    async def test_search_no_results(self, service):
        result = await service.search_books(query="NonExistentBookXYZ")
        assert len(result["items"]) == 0
        assert result["total"] == 0

    async def test_search_empty_query_raises(self, service):
        with pytest.raises(ValidationError, match="Search query must not be empty"):
            await service.search_books(query="")

    async def test_search_pagination_first_page(self, service):
        result = await service.search_books(query="Fiction", per_page=2)
        assert len(result["items"]) == 2
        assert result["page"] == 1
        assert result["per_page"] == 2
        assert result["total"] == 4

    async def test_search_pagination_second_page(self, service):
        result = await service.search_books(query="Fiction", page=2, per_page=2)
        assert result["page"] == 2
        assert len(result["items"]) == 2

    async def test_search_invalid_page(self, service):
        with pytest.raises(ValidationError, match="Page must be >= 1"):
            await service.search_books(query="test", page=0)

    async def test_search_invalid_per_page(self, service):
        with pytest.raises(ValidationError, match="per_page must be >= 1"):
            await service.search_books(query="test", per_page=0)

    async def test_search_per_page_clamped(self, service):
        result = await service.search_books(query="Fiction", per_page=500)
        assert result["per_page"] == 100

    async def test_search_flat_return(self, service):
        result = await service.search_books(query="Fiction", page=1, per_page=2)
        assert "items" in result
        assert "page" in result
        assert "per_page" in result
        assert "total" in result
        assert result["page"] == 1
        assert result["per_page"] == 2
        assert result["total"] == 4

    async def test_search_zero_results(self, service):
        result = await service.search_books(query="ZZZZNONEXISTENT")
        assert result["total"] == 0
        assert len(result["items"]) == 0

    async def test_summary_item_has_branches(self, service):
        result = await service.search_books(query="Gatsby")
        item = result["items"][0]
        assert "branches" in item
        assert isinstance(item["branches"], list)


@pytest.mark.asyncio
class TestBrowseBooks:
    async def test_browse_all(self, service):
        result = await service.browse_books()
        assert isinstance(result, dict)
        assert len(result["items"]) == 5
        assert result["total"] == 5

    async def test_browse_sort_by_title_asc(self, service):
        result = await service.browse_books(sort_by="title", sort_order="asc")
        titles = [r["title"] for r in result["items"]]
        assert titles == sorted(titles)

    async def test_browse_sort_by_title_desc(self, service):
        result = await service.browse_books(sort_by="title", sort_order="desc")
        titles = [r["title"] for r in result["items"]]
        assert titles == sorted(titles, reverse=True)

    async def test_browse_sort_by_year_asc(self, service):
        result = await service.browse_books(sort_by="published_year", sort_order="asc")
        ids = [r["biblio_id"] for r in result["items"]]
        assert ids == [4, 1, 3, 5, 2]

    async def test_browse_sort_by_year_desc(self, service):
        result = await service.browse_books(sort_by="published_year", sort_order="desc")
        ids = [r["biblio_id"] for r in result["items"]]
        assert ids == [2, 5, 3, 1, 4]

    async def test_browse_pagination(self, service):
        result = await service.browse_books(page=1, per_page=2)
        assert len(result["items"]) == 2
        assert result["total"] == 5
        assert result["page"] == 1
        assert result["per_page"] == 2

    async def test_browse_second_page_pagination(self, service):
        result = await service.browse_books(page=2, per_page=2)
        assert len(result["items"]) == 2
        assert result["page"] == 2
        assert result["total"] == 5

    async def test_browse_last_page(self, service):
        result = await service.browse_books(page=3, per_page=2)
        assert len(result["items"]) == 1
        assert result["page"] == 3

    async def test_browse_invalid_sort_by(self, service):
        with pytest.raises(ValidationError):
            await service.browse_books(sort_by="invalid_field")

    async def test_browse_invalid_sort_order(self, service):
        with pytest.raises(ValidationError):
            await service.browse_books(sort_order="invalid")

    async def test_browse_invalid_page(self, service):
        with pytest.raises(ValidationError):
            await service.browse_books(page=0)

    async def test_browse_flat_return(self, service):
        result = await service.browse_books(page=2, per_page=2)
        assert "page" in result
        assert "per_page" in result
        assert "total" in result
        assert "items" in result
        assert "sort_by" in result
        assert "sort_order" in result
        assert result["page"] == 2
        assert result["per_page"] == 2
        assert result["total"] == 5


@pytest.mark.asyncio
class TestBookDetails:
    async def test_get_details_found(self, service):
        detail = await service.get_book_details(1)
        assert isinstance(detail, dict)
        assert detail["biblio_id"] == 1
        assert detail["title"] == "The Great Gatsby"
        assert detail["authors"] == ["F. Scott Fitzgerald"]
        assert len(detail["copies"]) == 2

    async def test_get_details_with_copies(self, service):
        detail = await service.get_book_details(1)
        assert detail["copies"][0]["branch"] == "Main Library"
        assert detail["copies"][0]["status"] == "available"
        assert detail["copies"][1]["status"] == "checked_out"

    async def test_get_details_no_copies(self, service):
        detail = await service.get_book_details(2)
        assert len(detail["copies"]) == 1

    async def test_get_details_not_found(self, service):
        with pytest.raises(BookNotFoundError) as exc_info:
            await service.get_book_details(999)
        assert exc_info.value.biblio_id == 999

    async def test_get_details_all_fields(self, service):
        detail = await service.get_book_details(1)
        assert detail["biblio_id"] == 1
        assert detail["title"] == "The Great Gatsby"
        assert detail["publisher"] == "Scribner"
        assert detail["published_year"] == 1925
        assert detail["isbn"] == ["9780743273565"]
        assert "Fiction" in detail["categories"]
        assert detail["description"] is not None
        assert detail["total_copies"] == 2
        assert detail["available_copies"] == 1

    async def test_get_details_categories_is_list(self, service):
        detail = await service.get_book_details(1)
        assert isinstance(detail["categories"], list)
        assert len(detail["categories"]) > 0

    async def test_get_details_empty_copies_is_list(self, service):
        detail = await service.get_book_details(5)
        assert isinstance(detail["copies"], list)
        assert len(detail["copies"]) == 0

    async def test_get_details_callnumber_mapped(self, service):
        detail = await service.get_book_details(1)
        assert "callnumber" in detail["copies"][0]
        assert detail["copies"][0]["callnumber"] == "813.52 FIT"

    async def test_get_details_isbn_as_list(self, service):
        detail = await service.get_book_details(1)
        assert isinstance(detail["isbn"], list)
        assert detail["isbn"] == ["9780743273565"]

    async def test_detail_has_availability(self, service):
        detail = await service.get_book_details(1)
        assert "availability_synced_at" in detail
        assert "total_copies" in detail
        assert "available_copies" in detail


@pytest.mark.asyncio
class TestValidation:
    async def test_search_query_empty(self, service):
        with pytest.raises(ValidationError):
            await service.search_books(query="")
        with pytest.raises(ValidationError):
            await service.search_books(query="   ")

    async def test_search_page_zero(self, service):
        with pytest.raises(ValidationError, match="Page must be >= 1"):
            await service.search_books(query="test", page=0)

    async def test_search_per_page_zero(self, service):
        with pytest.raises(ValidationError, match="per_page must be >= 1"):
            await service.search_books(query="test", per_page=0)

    async def test_browse_page_zero(self, service):
        with pytest.raises(ValidationError, match="Page must be >= 1"):
            await service.browse_books(page=0)

    async def test_browse_per_page_zero(self, service):
        with pytest.raises(ValidationError, match="per_page must be >= 1"):
            await service.browse_books(per_page=0)

    async def test_browse_bad_sort_by(self, service):
        with pytest.raises(ValidationError):
            await service.browse_books(sort_by="rating")

    async def test_browse_bad_sort_order(self, service):
        with pytest.raises(ValidationError):
            await service.browse_books(sort_order="up")

    async def test_isbn_empty(self, service):
        with pytest.raises(ValidationError, match="ISBN must not be empty"):
            await service.search_by_isbn("")
        with pytest.raises(ValidationError, match="ISBN must not be empty"):
            await service.search_by_isbn("   ")
