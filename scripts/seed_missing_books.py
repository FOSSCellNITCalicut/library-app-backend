"""
Seed books that exist in Koha and are available, but are missing from the
`/items` browse endpoint — so the AvailabilityWorker never discovers them.

The rolling sync discovers biblios only by paging `/items`. A handful of
available books never appear there, so they are absent from our `books` /
`book_copies` tables. This one-shot script takes an explicit list of biblio_ids,
fetches their metadata + copies straight from Koha (reusing the exact same logic
as the sync workers), and seeds them in a FK-safe, idempotent way.

Reused (not re-implemented) so behaviour can't drift from the live workers:
  - metadata      : KohaClient.get_metadata + marc_parser        (MetadataWorker)
  - copy status   : AvailabilityWorker.compute_availability       (AvailabilityWorker)
  - date parsing  : availability_worker._parse_koha_date          (AvailabilityWorker)

Safety notes (verified against the schema + workers):
  - books are upserted BEFORE book_copies (book_copies.biblio_id FK).
  - search_vector and the copy aggregates (total/available/lib/mat_copies,
    availability_synced_at) are maintained by DB triggers — we never write them.
  - upserts are non-destructive: existing real metadata is never overwritten with
    a NULL or the "Unknown Title" placeholder (see _book_upsert).
  - the run is idempotent — safe to re-run (e.g. with the generated seed_errors.txt).

Usage (run from the repo root; needs a populated .env, same as the app):

  # dry run — fetch everything, write CSVs, DO NOT touch the DB
  python -m scripts.seed_missing_books --ids-file /path/to/missing_ids.txt

  # small live test first (fetch 5, write to DB)
  python -m scripts.seed_missing_books --ids-file /path/to/missing_ids.txt --limit 5 --commit

  # full seed
  python -m scripts.seed_missing_books --ids-file /path/to/missing_ids.txt --commit
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `app` importable when run as `python scripts/seed_missing_books.py`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.db.database import AsyncSessionLocal
from app.domains.books.models import Book, BookCopy
from app.domains.sync.marc_parser import marc_parser
from app.domains.sync.workers.availability_worker import (
    AvailabilityWorker,
    _parse_koha_date,
)
from app.integrations.koha.client import KohaClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_missing_books")

PLACEHOLDER_TITLE = "Unknown Title"  # matches AvailabilityWorker's placeholder


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #
def read_ids(path: Path) -> list[int]:
    """Read biblio_ids from a text file (one per line), deduped, order preserved."""
    ids: list[int] = []
    seen: set[int] = set()
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                bid = int(line)
            except ValueError:
                logger.warning("Skipping non-integer line: %r", line)
                continue
            if bid not in seen:
                seen.add(bid)
                ids.append(bid)
    return ids


# --------------------------------------------------------------------------- #
# Koha fetch (with retries; bulk-appropriate, unlike the 3s live-availability path)
# --------------------------------------------------------------------------- #
async def fetch_metadata(client: KohaClient, biblio_id: int, retries: int) -> dict | None:
    """MARC-in-JSON for a biblio. Returns None if Koha has no record (non-2xx)."""
    for attempt in range(1, retries + 1):
        try:
            return await client.get_metadata(biblio_id)  # dict | None (None on non-2xx)
        except (httpx.TimeoutException, httpx.RequestError) as e:
            if attempt >= retries:
                raise
            await asyncio.sleep(2 * attempt)
            logger.debug("metadata retry %s for %s: %s", attempt, biblio_id, e)
    return None


async def fetch_items(client: KohaClient, biblio_id: int, retries: int) -> list[dict]:
    """Items for a biblio via /biblios/{id}/items. [] when the biblio has none."""
    for attempt in range(1, retries + 1):
        try:
            resp = await client.client.get(f"/biblios/{biblio_id}/items")
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500 and attempt < retries:
                await asyncio.sleep(2 * attempt)
                continue
            raise
        except (httpx.TimeoutException, httpx.RequestError):
            if attempt >= retries:
                raise
            await asyncio.sleep(2 * attempt)
    return []


# --------------------------------------------------------------------------- #
# Build one book + its copies from Koha
# --------------------------------------------------------------------------- #
async def build_for_biblio(
    *,
    client: KohaClient,
    worker: AvailabilityWorker,
    biblio_id: int,
    retries: int,
    now: datetime,
) -> tuple[dict, list[dict], bool]:
    raw_meta = await fetch_metadata(client, biblio_id, retries)
    parsed = marc_parser.parse_marc_to_dict(raw_meta) if raw_meta else {}
    has_title = bool(parsed.get("title"))

    items = await fetch_items(client, biblio_id, retries)
    copies: list[dict] = []
    for item in items or []:
        item_id = item.get("item_id")
        branch = item.get("home_library_id")
        if item_id is None or not branch:
            logger.debug("skip item (missing id/branch) on biblio %s: %s", biblio_id, item)
            continue
        copies.append(
            {
                "item_id": item_id,
                "biblio_id": biblio_id,
                "branch": branch,
                "callnumber": item.get("callnumber"),
                "acquisition_date": _parse_koha_date(item.get("acquisition_date")),
                "external_id": item.get("external_id"),
                "status": worker.compute_availability(item),
                "last_seen_at": now,
            }
        )

    book = {
        "biblio_id": biblio_id,
        # title is NOT NULL; fall back to the same placeholder the worker uses
        "title": parsed.get("title") or PLACEHOLDER_TITLE,
        "authors": parsed.get("authors"),
        "isbn": parsed.get("isbns"),
        "publisher": parsed.get("publisher"),
        "published_year": parsed.get("year"),
        "categories": parsed.get("categories"),
        # description / cover_url / edition are intentionally left for the
        # GoogleBooksWorker enrichment scan to fill in later.
        "metadata_synced_at": now if has_title else None,
    }
    return book, copies, has_title


async def collect(
    *,
    ids: list[int],
    client: KohaClient,
    worker: AvailabilityWorker,
    concurrency: int,
    delay: float,
    retries: int,
    now: datetime,
) -> tuple[list[dict], list[dict], list[tuple[int, str]]]:
    sem = asyncio.Semaphore(concurrency)
    books: list[dict] = []
    copies: list[dict] = []
    errors: list[tuple[int, str]] = []
    total = len(ids)
    done = 0

    async def one(bid: int) -> None:
        nonlocal done
        async with sem:
            try:
                book, book_copies, has_title = await build_for_biblio(
                    client=client, worker=worker, biblio_id=bid, retries=retries, now=now
                )
                if not has_title and not book_copies:
                    # nothing to seed — likely a deleted/invalid biblio
                    errors.append((bid, "no metadata title and no items"))
                else:
                    books.append(book)
                    copies.extend(book_copies)
            except Exception as e:  # noqa: BLE001 — record and continue
                errors.append((bid, repr(e)))
            finally:
                done += 1
                if done % 100 == 0 or done == total:
                    logger.info("fetched %s/%s (books=%s copies=%s errors=%s)",
                                done, total, len(books), len(copies), len(errors))
                if delay:
                    await asyncio.sleep(delay)

    await asyncio.gather(*(one(b) for b in ids))
    return books, copies, errors


# --------------------------------------------------------------------------- #
# CSV output
# --------------------------------------------------------------------------- #
def _arr(value: list[str] | None) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def write_csvs(out_dir: Path, books: list[dict], copies: list[dict]) -> tuple[Path, Path]:
    books_path = out_dir / "books_seed.csv"
    copies_path = out_dir / "book_copies_seed.csv"

    with books_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["biblio_id", "title", "authors", "isbn", "publisher",
             "published_year", "categories", "metadata_synced_at"]
        )
        for b in books:
            w.writerow([
                b["biblio_id"],
                b["title"],
                _arr(b["authors"]),
                _arr(b["isbn"]),
                b["publisher"] or "",
                b["published_year"] if b["published_year"] is not None else "",
                _arr(b["categories"]),
                b["metadata_synced_at"].isoformat() if b["metadata_synced_at"] else "",
            ])

    with copies_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["item_id", "biblio_id", "branch", "callnumber",
             "acquisition_date", "status", "external_id", "last_seen_at"]
        )
        for c in copies:
            w.writerow([
                c["item_id"],
                c["biblio_id"],
                c["branch"],
                c["callnumber"] or "",
                c["acquisition_date"].isoformat() if c["acquisition_date"] else "",
                c["status"],
                c["external_id"] or "",
                c["last_seen_at"].isoformat(),
            ])

    return books_path, copies_path


# --------------------------------------------------------------------------- #
# DB upsert (idempotent, non-destructive; FK-safe: books then copies)
# --------------------------------------------------------------------------- #
def _chunked(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


async def _upsert_books(session, batch: list[dict]) -> None:
    for b in batch:
        stmt = insert(Book).values(**b)
        excl = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[Book.biblio_id],
            set_={
                # never overwrite a real title with the placeholder
                "title": func.coalesce(func.nullif(excl.title, PLACEHOLDER_TITLE), Book.title),
                # never overwrite existing values with NULLs from a partial fetch
                "authors": func.coalesce(excl.authors, Book.authors),
                "isbn": func.coalesce(excl.isbn, Book.isbn),
                "publisher": func.coalesce(excl.publisher, Book.publisher),
                "published_year": func.coalesce(excl.published_year, Book.published_year),
                "categories": func.coalesce(excl.categories, Book.categories),
                "metadata_synced_at": func.coalesce(
                    excl.metadata_synced_at, Book.metadata_synced_at
                ),
            },
        )
        await session.execute(stmt)


async def _upsert_copies(session, batch: list[dict]) -> None:
    for c in batch:
        stmt = insert(BookCopy).values(**c)
        excl = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[BookCopy.item_id],
            set_={
                "branch": excl.branch,
                "callnumber": excl.callnumber,
                "acquisition_date": excl.acquisition_date,
                "status": excl.status,
                "external_id": func.coalesce(excl.external_id, BookCopy.external_id),
                "last_seen_at": excl.last_seen_at,
            },
        )
        await session.execute(stmt)


async def commit_all(books: list[dict], copies: list[dict], batch_size: int) -> None:
    # All books first (satisfies the book_copies FK), then all copies.
    async with AsyncSessionLocal() as session:
        for chunk in _chunked(books, batch_size):
            await _upsert_books(session, chunk)
            await session.commit()
        logger.info("upserted %s books", len(books))

        for chunk in _chunked(copies, batch_size):
            await _upsert_copies(session, chunk)
            await session.commit()
        logger.info("upserted %s copies (aggregates recomputed by trigger)", len(copies))


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
async def main_async(args: argparse.Namespace) -> None:
    ids = read_ids(Path(args.ids_file))
    if args.limit:
        ids = ids[: args.limit]
    logger.info("loaded %s biblio_ids from %s", len(ids), args.ids_file)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    client = KohaClient()
    worker = AvailabilityWorker(client)  # reused only for compute_availability
    try:
        books, copies, errors = await collect(
            ids=ids, client=client, worker=worker,
            concurrency=args.concurrency, delay=args.delay, retries=args.retries, now=now,
        )
    finally:
        await client.aclose()

    logger.info("fetch complete: %s books, %s copies, %s errors",
                len(books), len(copies), len(errors))

    books_path, copies_path = write_csvs(out_dir, books, copies)
    logger.info("wrote %s and %s", books_path, copies_path)

    if errors:
        (out_dir / "seed_errors.txt").write_text(
            "\n".join(str(b) for b, _ in errors), encoding="utf-8"
        )
        (out_dir / "seed_errors_detail.txt").write_text(
            "\n".join(f"{b}\t{msg}" for b, msg in errors), encoding="utf-8"
        )
        logger.warning("%s biblio_ids failed — re-run with --ids-file %s",
                       len(errors), out_dir / "seed_errors.txt")

    if args.commit:
        await commit_all(books, copies, args.batch_size)
        logger.info("DONE — committed to the database")
    else:
        logger.info("DONE — dry run (no --commit); database untouched")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Koha books missing from /items browse.")
    p.add_argument("--ids-file", required=True, help="text file of biblio_ids, one per line")
    p.add_argument("--out-dir", default="seed_output", help="where to write CSVs / error lists")
    p.add_argument("--concurrency", type=int, default=5, help="parallel Koha requests (be gentle)")
    p.add_argument("--delay", type=float, default=0.0, help="seconds to wait after each request")
    p.add_argument("--retries", type=int, default=3, help="retries per Koha call on transient errors")
    p.add_argument("--limit", type=int, default=0, help="only process the first N ids (0 = all)")
    p.add_argument("--batch-size", type=int, default=200, help="rows per DB commit")
    p.add_argument("--commit", action="store_true", help="actually write to the DB (default: dry run)")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
