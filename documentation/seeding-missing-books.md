# Seeding books missing from the `/items` browse endpoint

## The problem

The `AvailabilityWorker` discovers biblios **only** by paging Koha's `/items` browse
endpoint. A subset of books that genuinely exist in Koha and are available to borrow
**never appear in `/items`**, so the worker never discovers them — they end up absent
from our `books` / `book_copies` tables and are invisible to search and browse.

This was found while seeding the catalog: ~200 such books turned up in a 4k sample
(and inserting their copies raised foreign-key errors, because no parent `books` row
existed). A full sweep produced a list of **3,435** missing biblio_ids spanning
916 → 74617.

## The fix

A one-shot script — [`scripts/seed_missing_books.py`](../scripts/seed_missing_books.py) —
takes an explicit list of biblio_ids and fetches each book's metadata + copies straight
from Koha, then seeds them into our tables.

It **reuses the live workers' own logic** (imported, not copied, so behaviour can't drift):

| Data | Reused from |
|---|---|
| metadata (title, authors, ISBN, publisher, year, categories) | `KohaClient.get_metadata` + `marc_parser` (MetadataWorker) |
| copy status (`Available` / `Not Available`) | `AvailabilityWorker.compute_availability` |
| acquisition-date parsing | `availability_worker._parse_koha_date` |

### Why nothing breaks after seeding

- **FK-safe order** — all `books` are upserted **before** any `book_copies`
  (`book_copies.biblio_id` → `books.biblio_id`), which is exactly the FK error the
  naive approach hit.
- **Trigger-owned columns are never written** — `search_vector` and the aggregates
  (`total_copies` / `available_copies` / `lib_copies` / `mat_copies`,
  `availability_synced_at`) are populated by the existing DB triggers on insert.
- **Non-destructive, idempotent upserts** — on conflict it `coalesce`s, so a real title
  is never overwritten by the `"Unknown Title"` placeholder and existing metadata is
  never nulled by a partial fetch. Safe to re-run.
- `description` / `cover_url` are intentionally left NULL — the `GoogleBooksWorker`
  enrichment scan fills them by ISBN like it does for every other book.

## Usage

Run from the repo root with the normal `.env` present:

```bash
# dry run — fetch everything, write CSVs, do NOT touch the DB
python -m scripts.seed_missing_books --ids-file /path/to/missing_ids.txt

# small live test first
python -m scripts.seed_missing_books --ids-file /path/to/missing_ids.txt --limit 5 --commit

# full seed
python -m scripts.seed_missing_books --ids-file /path/to/missing_ids.txt --commit
```

Flags: `--concurrency` (parallel Koha requests, default 5), `--delay`, `--retries`,
`--limit`, `--batch-size`, `--out-dir`. Failed ids are written to
`<out-dir>/seed_errors.txt` — re-run pointing `--ids-file` at that to finish them.

## Result of the initial run (3,435 ids)

- **3,210 books seeded** (+6,322 copies); catalogue 46,239 → 49,449. Verified in the DB:
  aggregates computed by trigger, `search_vector` populated, books now searchable.
- **225 not seeded, and correctly so:**
  - **215** — deleted/invalid in Koha (404 for both metadata and items — nothing to seed).
  - **10** — a persistent Koha **500** on their `/items` endpoint (Koha-side bug, retryable
    later): `71636, 73212, 73216, 73217, 73249, 73928, 74028, 74079, 74102, 74150`.

## Caveats / follow-ups

- These books are invisible to the `AvailabilityWorker` (that's the root cause), so their
  copy status is a **point-in-time snapshot** from seed time — it won't auto-refresh like
  normally-synced books. The per-book "Check Live Availability" path still works on the
  detail page.
- If the `last_seen_at` **ghost-inventory reaper** (a TODO in `documentation/issues.md`)
  is ever implemented, it must exclude these seeded copies — the availability worker will
  never re-touch them, so their `last_seen_at` stays fixed and they would otherwise be
  wrongly reaped after 30 days.
- Open question: whether to also enqueue these biblios into `metadata_queue` so future
  rolling refreshes treat them like normally-discovered books.
