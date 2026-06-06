import logging

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class KohaError(Exception):
    """Base class for Koha client errors."""


class KohaServerError(KohaError):
    """Raised when Koha returns a 5xx response."""


class KohaClient:
    def __init__(self):
        self.base_url = settings.KOHA_BASE_URL

        self.client = httpx.AsyncClient(
            base_url=settings.KOHA_BASE_URL,
            timeout=30,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get_items(self, page: int):
        """
        Fetches a page of items from Koha. This is processed by AvailabilityWorker.
        Returns the parsed JSON list on success.
        Raises KohaServerError on 5xx.
        Raises httpx.HTTPStatusError on other non-2xx responses.
        """
        try:
            response = await self.client.get(
                "/items",
                params={
                    "_page": page,
                    "_per_page": settings.ITEMS_PER_PAGE,
                },
            )
            response.raise_for_status()
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                raise KohaServerError(f"Koha /items returned {e.response.status_code} on page {page}") from e
            
            raise

        return response.json()

    async def get_availability(self, biblio_id: int):
        """
        Use when clicking "Check Live Availability" on the frontend. Returns the
        live availability status instead of cached status from database.
        """
        try:
            response = await self.client.get(
                f"/biblios/{biblio_id}/items",
                timeout=settings.KOHA_AVAILABILITY_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        
        except httpx.TimeoutException:
            logger.warning("Timeout fetching live availability for biblio_id=%s", biblio_id)
            return None
        
        except httpx.HTTPStatusError as e:
            logger.warning(
                "HTTP %s fetching live availability for biblio_id=%s",
                e.response.status_code,
                biblio_id,
            )
            return None

        return response.json()

    async def get_metadata(self, biblio_id: int):
        """
        Returns data in MARC format for the given biblio_id. Must be converted
        to a dict before being stored in the database.
        """
        try:
            response = await self.client.get(
                f"/biblios/{biblio_id}",
                headers={"Accept": "application/marc-in-json"},
            )
            response.raise_for_status()
        
        except httpx.HTTPStatusError as e:
            logger.warning(
                "HTTP %s fetching metadata for biblio_id=%s",
                e.response.status_code,
                biblio_id,
            )
            return None

        return response.json()


koha_client = KohaClient()
