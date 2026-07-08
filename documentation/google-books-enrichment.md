## Google Books Enrichment Worker

### Purpose

Fetch cover URLs and descriptions from the Google Books API for books that have ISBNs but are missing enrichment data (cover_url and/or description).

### Design: Scan-Based Worker (No Queue)

Google Books data changes rarely, and we need to both backfill existing books and auto-enrich new ones. A periodic scan-based worker is simpler and more robust than a queue-based approach — no new table, no hooks in existing workers, automatic backfill.

### Flow

```
AvailabilityWorker (discovers new biblio_id)
  → enqueues metadata job
    → MetadataWorker (processes MARC, populates ISBN, title, etc.)
      → GoogleBooksWorker (next scan cycle picks up the ISBN)
```

No explicit hook needed — the scan query naturally detects books once their ISBN is populated.

---

### Implementation

#### 1. Configuration (`app/core/config.py`)

```
GOOGLE_BOOKS_API_KEYS: str              # comma-separated list of keys (from .env); required (non-empty)
GOOGLE_BOOKS_WORKER_DELAY: int = 60     # seconds between scan cycles
GOOGLE_BOOKS_SCAN_BATCH_SIZE: int = 10  # books per cycle
```

Multiple keys are rotated/failed-over: on a 429 the client tries the next key; quota is tracked per key. **An empty `GOOGLE_BOOKS_API_KEYS` makes the app fail to start** (the client is built at import).

#### 2. Google Books Client (`app/integrations/google_books/client.py`)

Async httpx client. Public method:

```
fetch_by_isbn(isbn: str) -> dict | None
```

Calls `GET https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&key={api_key}`.

Returns a dict with a subset of `cover_url` (from `volumeInfo.imageLinks.thumbnail`, upgraded to https) and/or `description` (from `volumeInfo.description`); returns `None` **only** when there is no matching volume.

Quota: `DailyQuotaTracker` (limit 1000/day per key, resets by Pacific date). Before each request the least-used key is chosen.

Errors are raised as exceptions (not returned):

- `RateLimitedError` — all keys returned 429 (transient rate limit).
- `QuotaExhaustedError` — all keys exhausted their daily quota.
- `GoogleBooksFetchError` — other HTTP/network failures (5xx, 403, timeout, bad JSON). Raised (not swallowed) so the worker can retry later without burning the retry budget.

#### 3. Worker (`app/workers/enrichment/google_books_worker.py`)

Same asyncio-loop pattern as existing workers.

**Each cycle:**

1. **Query** books needing enrichment:
   ```sql
   SELECT biblio_id, isbn FROM books
   WHERE isbn IS NOT NULL
     AND array_length(isbn, 1) > 0
     AND google_try_count < 2
     AND (cover_url IS NULL OR description IS NULL)
   ORDER BY metadata_synced_at ASC NULLS FIRST
   LIMIT {batch_size}
   ```
   `google_try_count < 2` caps total attempts per book; `NULLS FIRST` picks never-processed books first.

2. **Pick one ISBN** per book (`pick_isbn`): strip `-`/`space`, keep digit/`x` candidates with length >= 10, prefer the longest. Books with no valid ISBN are marked `metadata_synced_at` (skipped) without incrementing `google_try_count`.

3. **Call API**, then **update and commit the row immediately** (per-book commit):
   - On data: set available fields + `metadata_synced_at` + `google_try_count + 1`.
   - On `None` (no match): same update but no fields filled; `google_try_count` still increments so the book is excluded after 2 attempts.

4. **Backoff / sleep**:
   - `RateLimitedError` → break batch, exponential backoff (1s → 300s cap). After 5 consecutive rate-limited cycles, sleep until midnight Pacific (treated as quota exhausted).
   - `QuotaExhaustedError` → sleep until midnight Pacific.
   - `GoogleBooksFetchError` → log and skip the book (no `google_try_count` increment); retried on a later cycle.
   - Otherwise: wait `GOOGLE_BOOKS_WORKER_DELAY` between cycles.

#### 4. Startup (`app/main.py`)

Started in the `lifespan` handler regardless of `SEED_DATA` (only needs the DB). The httpx client is closed on shutdown. Shutdown cancels the task alongside the others.

---

### ISBN Selection Strategy

| Priority | Rule |
|----------|------|
| 1 | Strip hyphens and whitespace from all candidates |
| 2 | Keep only digit / `x` (case-insensitive) candidates with length >= 10 |
| 3 | Prefer the longest candidate (ISBN-13 over ISBN-10) |

---

### Key Decisions

| Concern | Decision |
|---------|----------|
| Queue vs Scan | **Scan** — simpler, no new table, auto-backfills, resilient to downtime |
| Hook into metadata worker | **No** — scan naturally picks up books once ISBN is populated |
| Re-fetch policy | Skip when both `cover_url` and `description` are set; capped at `google_try_count < 2` |
| Rate limits | Respect 429s with exponential backoff; 5 consecutive → sleep to midnight PT |
| Quota | 1000 req/day per key; sleep until midnight PT when all keys exhausted |
| Transient vs not-found | Not-found (`None`) burns retry budget; transient errors (`GoogleBooksFetchError`) do NOT and are retried later |
| Multiple keys | Comma-separated `GOOGLE_BOOKS_API_KEYS`; rotated/failed-over |
| Commit strategy | Per-book commit — a mid-batch quota error loses no prior work |
| New DB table | **None** |
| Migration | **None** |
| Startup dependency | Only DB (not Koha), runs even when `SEED_DATA=False` |

---

### What It Does NOT Handle

- **Real-time enrichment**: within one scan cycle (~60s) after ISBN is populated; acceptable since cover/description are not time-critical.
- **On-demand refresh**: not needed; clearing `cover_url`/`description` makes the worker pick the book up again (subject to `google_try_count`).
- **Multiple Google Books matches**: takes the first result (ISBN lookup is effectively unique).
- **Per-key `Retry-After`**: the client does not parse `Retry-After`; backoff is driven by the worker's own schedule.
