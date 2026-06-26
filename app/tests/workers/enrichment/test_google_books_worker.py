from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.google_books.client import RateLimitedError
from app.workers.enrichment.google_books_worker import pick_isbn


class TestPickISBN:
    def test_prefers_longest(self):
        assert pick_isbn(["10", "9780141439518"]) == "9780141439518"

    def test_strips_hyphens(self):
        assert pick_isbn(["978-0-14-143951-8"]) == "9780141439518"

    def test_strips_spaces(self):
        assert pick_isbn(["978 0 14 143951 8"]) == "9780141439518"

    def test_returns_none_for_empty_list(self):
        assert pick_isbn([]) is None

    def test_returns_none_for_all_none(self):
        assert pick_isbn([None, None]) is None

    def test_returns_none_for_all_invalid(self):
        assert pick_isbn(["abc", "12"]) is None

    def test_skips_non_digit_after_cleanup(self):
        assert pick_isbn(["978-abc-123"]) is None

    def test_skips_short_isbns(self):
        assert pick_isbn(["123456789"]) is None

    def test_picks_only_valid_from_mixed(self):
        assert pick_isbn(["invalid", "9780141439518"]) == "9780141439518"

    def test_single_isbn(self):
        assert pick_isbn(["9780141439518"]) == "9780141439518"

    def test_isbn10_with_x_is_rejected(self):
        assert pick_isbn(["014143951X"]) is None


@pytest.mark.asyncio
class TestGoogleBooksWorkerBatch:
    @patch("app.workers.enrichment.google_books_worker.google_books_client")
    @patch("app.workers.enrichment.google_books_worker.AsyncSessionLocal")
    async def test_processes_books_needing_enrichment(self, mock_session_factory, mock_client):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.all.return_value = [
            (1, ["9780141439518"]),
            (2, ["9780061120084", "0061120088"]),
        ]
        mock_session.execute.return_value = mock_result

        mock_client.fetch_by_isbn = AsyncMock(side_effect=[
            {"cover_url": "https://example.com/cover1.jpg", "description": "Desc 1"},
            {"cover_url": "https://example.com/cover2.jpg"},
        ])

        from app.workers.enrichment.google_books_worker import GoogleBooksWorker
        worker = GoogleBooksWorker()
        rate_limited = await worker._process_batch()

        assert rate_limited is False
        assert mock_session.execute.call_count == 3
        assert mock_client.fetch_by_isbn.call_count == 2
        mock_session.commit.assert_awaited_once()

    @patch("app.workers.enrichment.google_books_worker.AsyncSessionLocal")
    async def test_skips_when_no_books_need_enrichment(self, mock_session_factory):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        from app.workers.enrichment.google_books_worker import GoogleBooksWorker
        worker = GoogleBooksWorker()
        await worker._process_batch()

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_not_called()

    @patch("app.workers.enrichment.google_books_worker.pick_isbn")
    @patch("app.workers.enrichment.google_books_worker.AsyncSessionLocal")
    async def test_skips_books_without_valid_isbn(self, mock_session_factory, mock_pick_isbn):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.all.return_value = [(1, ["invalid"])]
        mock_session.execute.return_value = mock_result

        mock_pick_isbn.return_value = None

        from app.workers.enrichment.google_books_worker import GoogleBooksWorker
        worker = GoogleBooksWorker()
        rate_limited = await worker._process_batch()

        assert rate_limited is False
        mock_session.commit.assert_called_once()

    @patch("app.workers.enrichment.google_books_worker.google_books_client")
    @patch("app.workers.enrichment.google_books_worker.AsyncSessionLocal")
    async def test_stops_batch_on_rate_limit(self, mock_session_factory, mock_client):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.all.return_value = [
            (1, ["9780141439518"]),
            (2, ["9780061120084"]),
        ]
        mock_session.execute.return_value = mock_result

        mock_client.fetch_by_isbn = AsyncMock(side_effect=RateLimitedError())

        from app.workers.enrichment.google_books_worker import GoogleBooksWorker
        worker = GoogleBooksWorker()
        rate_limited = await worker._process_batch()

        assert rate_limited is True
        assert mock_client.fetch_by_isbn.call_count == 1


@pytest.mark.asyncio
class TestGoogleBooksClient:
    @patch("app.integrations.google_books.client.httpx.AsyncClient")
    async def test_parse_valid_response(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{
                "volumeInfo": {
                    "imageLinks": {"thumbnail": "http://example.com/cover.jpg"},
                    "description": "A great book",
                }
            }]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        from app.integrations.google_books.client import GoogleBooksClient
        client = GoogleBooksClient(api_key="test-key")
        result = await client.fetch_by_isbn("9780141439518")

        assert result == {
            "cover_url": "https://example.com/cover.jpg",
            "description": "A great book",
        }

    @patch("app.integrations.google_books.client.httpx.AsyncClient")
    async def test_returns_none_on_empty_response(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": []}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        from app.integrations.google_books.client import GoogleBooksClient
        client = GoogleBooksClient(api_key="test-key")
        result = await client.fetch_by_isbn("9780141439518")

        assert result is None

    @patch("app.integrations.google_books.client.httpx.AsyncClient")
    async def test_raises_on_429(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Quota exceeded"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        from app.integrations.google_books.client import GoogleBooksClient
        client = GoogleBooksClient(api_key="test-key")
        with pytest.raises(RateLimitedError):
            await client.fetch_by_isbn("9780141439518")

    @patch("app.integrations.google_books.client.httpx.AsyncClient")
    async def test_returns_none_on_invalid_isbn(self, mock_client_class):
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        from app.integrations.google_books.client import GoogleBooksClient
        client = GoogleBooksClient(api_key="test-key")
        result = await client.fetch_by_isbn("abc")

        assert result is None
        mock_client.get.assert_not_called()

    @patch("app.integrations.google_books.client.httpx.AsyncClient")
    async def test_prefers_extra_large_over_thumbnail(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{
                "volumeInfo": {
                    "imageLinks": {
                        "thumbnail": "http://example.com/thumb.jpg",
                        "extraLarge": "http://example.com/xl.jpg",
                    }
                }
            }]
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        from app.integrations.google_books.client import GoogleBooksClient
        client = GoogleBooksClient(api_key="test-key")
        result = await client.fetch_by_isbn("9780141439518")

        assert result["cover_url"] == "https://example.com/xl.jpg"

    @patch("app.integrations.google_books.client.httpx.AsyncClient")
    async def test_upgrades_thumbnail_zoom(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{
                "volumeInfo": {
                    "imageLinks": {
                        "thumbnail": "http://example.com/cover.jpg?zoom=1&other=1",
                    }
                }
            }]
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        from app.integrations.google_books.client import GoogleBooksClient
        client = GoogleBooksClient(api_key="test-key")
        result = await client.fetch_by_isbn("9780141439518")

        assert result["cover_url"] == "https://example.com/cover.jpg?zoom=3&other=1"

    @patch("app.integrations.google_books.client.httpx.AsyncClient")
    async def test_falls_back_to_small_thumbnail(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{
                "volumeInfo": {
                    "imageLinks": {
                        "smallThumbnail": "http://example.com/small.jpg",
                    }
                }
            }]
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        from app.integrations.google_books.client import GoogleBooksClient
        client = GoogleBooksClient(api_key="test-key")
        result = await client.fetch_by_isbn("9780141439518")

        assert result["cover_url"] == "https://example.com/small.jpg"
