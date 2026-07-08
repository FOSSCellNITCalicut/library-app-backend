import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)

DAILY_QUOTA_LIMIT = 1000
MAX_KEY_CONSECUTIVE_429 = 5


class RateLimitedError(Exception):
    """Raised when all keys return 429 and none have quota remaining."""


class QuotaExhaustedError(Exception):
    """Raised when all API keys have exhausted their daily quota."""


class GoogleBooksFetchError(Exception):
    """Raised on transient/HTTP/network failures (not 429, not quota)."""


PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


class DailyQuotaTracker:
    def __init__(self, limit: int = DAILY_QUOTA_LIMIT):
        self._limit = limit
        self._count = 0
        self._date = datetime.now(PACIFIC_TZ).date()
        self._consecutive_429 = 0
        self._disabled = False

    def _reset_if_new_day(self) -> None:
        today = datetime.now(PACIFIC_TZ).date()
        if today != self._date:
            self._count = 0
            self._consecutive_429 = 0
            self._disabled = False
            self._date = today

    @property
    def count(self) -> int:
        self._reset_if_new_day()
        return self._count

    def check(self) -> None:
        self._reset_if_new_day()
        if self._count >= self._limit:
            raise QuotaExhaustedError()

    def increment(self) -> None:
        self._reset_if_new_day()
        self._count += 1

    def mark_429(self) -> None:
        self._reset_if_new_day()
        self._consecutive_429 += 1
        if self._consecutive_429 >= MAX_KEY_CONSECUTIVE_429:
            self._disabled = True

    def mark_success(self) -> None:
        self._reset_if_new_day()
        self._consecutive_429 = 0

    @property
    def is_disabled(self) -> bool:
        self._reset_if_new_day()
        return self._disabled


class GoogleBooksClient:
    BASE_URL = "https://www.googleapis.com/books/v1"

    @staticmethod
    def _parse_keys(raw: str) -> list[str]:
        return [k.strip() for k in raw.split(",") if k.strip()]

    def __init__(self, api_keys: list[str] | None = None):
        keys = api_keys if api_keys is not None else self._parse_keys(settings.GOOGLE_BOOKS_API_KEYS)
        if not keys:
            raise ValueError("At least one Google Books API key is required")
        self._key_trackers: list[tuple[str, DailyQuotaTracker]] = [
            (key, DailyQuotaTracker()) for key in keys
        ]
        self.client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=15)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def fetch_by_isbn(self, isbn: str) -> dict | None:
        isbn_clean = isbn.replace("-", "").replace(" ", "")
        if not isbn_clean.replace("x", "").replace("X", "").isdigit():
            logger.warning("Invalid ISBN (non-digit after cleanup): %s", isbn)
            return None

        self._key_trackers.sort(key=lambda kt: kt[1].count)

        for key, tracker in self._key_trackers:
            if tracker.is_disabled:
                logger.debug(
                    "Key %s... disabled for the day after %d consecutive 429s, skipping",
                    key[:8],
                    MAX_KEY_CONSECUTIVE_429,
                )
                continue

            try:
                tracker.check()
            except QuotaExhaustedError:
                continue

            try:
                response = await self.client.get(
                    "/volumes",
                    params={"q": f"isbn:{isbn_clean}", "key": key},
                )

                tracker.increment()

                if response.status_code == 429:
                    was_disabled = tracker.is_disabled
                    tracker.mark_429()
                    if tracker.is_disabled and not was_disabled:
                        logger.warning(
                            "Key %s... disabled for the day after %d consecutive 429s",
                            key[:8],
                            MAX_KEY_CONSECUTIVE_429,
                        )
                    else:
                        logger.warning(
                            "Key %s... rate limited (429), trying next key",
                            key[:8],
                        )
                    continue

                tracker.mark_success()
                response.raise_for_status()

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "Google Books API HTTP %s for ISBN %s: %s",
                    e.response.status_code, isbn_clean, e.response.text[:200],
                )
                raise GoogleBooksFetchError(str(e)) from e

            except httpx.RequestError as e:
                logger.warning("Google Books API request failed for ISBN %s: %s", isbn_clean, e)
                raise GoogleBooksFetchError(str(e)) from e

            data = response.json()
            items = data.get("items")
            if not items:
                return None

            volume_info = items[0].get("volumeInfo", {})
            result = {}

            image_links = volume_info.get("imageLinks", {})
            cover_url = None
            thumbnail_url = image_links.get("thumbnail")
            if thumbnail_url:
                cover_url = thumbnail_url.replace("http://", "https://")

            if cover_url:
                result["cover_url"] = cover_url

            raw_description = volume_info.get("description")
            if raw_description:
                result["description"] = raw_description

            return result if result else None

        all_unavailable = all(
            kt[1].is_disabled or kt[1].count >= DAILY_QUOTA_LIMIT
            for kt in self._key_trackers
        )
        if all_unavailable:
            raise QuotaExhaustedError()
        raise RateLimitedError()


google_books_client = GoogleBooksClient()
