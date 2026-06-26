import logging

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class RateLimitedError(Exception):
    """Raised when Google Books API returns 429."""


class GoogleBooksClient:
    BASE_URL = "https://www.googleapis.com/books/v1"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.GOOGLE_BOOKS_API_KEY
        self.client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=15)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def fetch_by_isbn(self, isbn: str) -> dict | None:
        # replace special character if present in isbn
        isbn_clean = isbn.replace("-", "").replace(" ", "")
        if not isbn_clean.isdigit():
            logger.warning("Invalid ISBN (non-digit after cleanup): %s", isbn)
            return None

        try:
            response = await self.client.get(
                "/volumes",
                params={"q": f"isbn:{isbn_clean}", "key": self.api_key},
            )

            if response.status_code == 429:
                logger.warning("Google Books API rate limited (429): %s", response.text[:300])
                raise RateLimitedError()

            response.raise_for_status()

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Google Books API HTTP %s for ISBN %s: %s",
                e.response.status_code, isbn_clean, e.response.text[:200],
            )
            return None

        except httpx.RequestError as e:
            logger.warning("Google Books API request failed for ISBN %s: %s", isbn_clean, e)
            return None

        data = response.json()
        items = data.get("items")
        if not items:
            return None

        volume_info = items[0].get("volumeInfo", {})
        result = {}

        image_links = volume_info.get("imageLinks", {})
        cover_url = None
        for key in ("extraLarge", "large", "medium", "thumbnail", "smallThumbnail"):
            url = image_links.get(key)
            if url:
                cover_url = url.replace("http://", "https://")
                if key == "thumbnail":
                    cover_url = cover_url.replace("zoom=1", "zoom=3")
                break

        if cover_url:
            result["cover_url"] = cover_url

        raw_description = volume_info.get("description")
        if raw_description:
            result["description"] = raw_description

        return result if result else None


google_books_client = GoogleBooksClient()
