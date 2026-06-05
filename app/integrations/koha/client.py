import httpx

from app.core.config import settings

class KohaClient:
    def __init__(self):
        self.base_url = settings.KOHA_BASE_URL

        self.client = httpx.AsyncClient(
            base_url=settings.KOHA_BASE_URL,
            timeout=30
        )

    async def get_items(self, page: int):
        response = await self.client.get(
            "/items",
            params={
                "_page": page,
                "_per_page": settings.ITEMS_PER_PAGE
            }
        )
        response.raise_for_status()
        
        return response.json()
    
    async def get_biblio(self, biblio_id: int):
        response = await self.client.get(
            f"/public/biblios/{biblio_id}/items"
        )

        response.raise_for_status()

        return response.json()

koha_client = KohaClient()
