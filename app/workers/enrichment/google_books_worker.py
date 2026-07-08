import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.domains.books.models import Book
from app.integrations.google_books.client import RateLimitedError, google_books_client


logger = logging.getLogger(__name__)

MAX_BACKOFF = 300


def _isbn_all_digits(s: str) -> bool:
    return all(c.isdigit() or c.lower() == "x" for c in s)


def pick_isbn(isbns: list[str]) -> str | None:
    cleaned = [s.replace("-", "").replace(" ", "") for s in isbns if s]
    cleaned = [s for s in cleaned if _isbn_all_digits(s) and len(s) >= 10]
    if not cleaned:
        return None
    cleaned.sort(key=len, reverse=True)
    return cleaned[0]


class GoogleBooksWorker:
    async def run(self) -> None:
        backoff = 1

        while True:
            try:
                rate_limited = await self._process_batch()
                if rate_limited:
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    logger.warning("Rate limited, backing off for %ss", backoff)
                    await asyncio.sleep(backoff)
                    continue
                backoff = 1

            except Exception as e:
                logger.exception("Unexpected error in google books worker: %s", e)

            await asyncio.sleep(settings.GOOGLE_BOOKS_WORKER_DELAY)

    async def _process_batch(self) -> bool:
        rate_limited = False
        logger.info("Google Books worker scanning for books needing enrichment")

        async with AsyncSessionLocal() as session:
            stmt = (
                select(Book.biblio_id, Book.isbn)
                .where(
                    Book.isbn.isnot(None),
                    func.array_length(Book.isbn, 1) > 0,
                    (Book.cover_url.is_(None)) | (Book.description.is_(None)),
                )
                .order_by(Book.metadata_synced_at.asc().nullsfirst())
                .limit(settings.GOOGLE_BOOKS_SCAN_BATCH_SIZE)
            )
            result = await session.execute(stmt)
            rows = result.all()

            if not rows:
                return False

            for biblio_id, isbns in rows:
                isbn = pick_isbn(isbns)
                if not isbn:
                    await session.execute(
                        update(Book)
                        .where(Book.biblio_id == biblio_id)
                        .values(metadata_synced_at=datetime.now(timezone.utc))
                    )
                    continue

                try:
                    book_data = await google_books_client.fetch_by_isbn(isbn)
                except RateLimitedError:
                    rate_limited = True
                    break

                update_values = {"metadata_synced_at": datetime.now(timezone.utc)}
                if book_data:
                    if "cover_url" in book_data:
                        update_values["cover_url"] = book_data["cover_url"]
                    if "description" in book_data:
                        update_values["description"] = book_data["description"]

                    logger.info(
                        "Enriched biblio_id=%s via ISBN %s: cover=%s description=%s",
                        biblio_id,
                        isbn,
                        "yes" if "cover_url" in book_data else "no",
                        "yes" if "description" in book_data else "no",
                    )

                await session.execute(
                    update(Book).where(Book.biblio_id == biblio_id).values(**update_values)
                )

            await session.commit()

        return rate_limited
