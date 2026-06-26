## Google Books Enrichment Worker

### Purpose

Fetch cover URLs and descriptions from the Google Books API for books that have ISBNs but are missing enrichment data.

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

Add to `Settings`:

```
GOOGLE_BOOKS_API_KEY: str               # from .env
GOOGLE_BOOKS_WORKER_DELAY: int = 60      # seconds between scan cycles
GOOGLE_BOOKS_SCAN_BATCH_SIZE: int = 10   # books per cycle
```

#### 2. Google Books Client (`app/integrations/google_books/client.py`)

Async httpx client with a single public method:

```
fetch_book_by_isbn(isbn: str) -> GoogleBookData | None
```

Calls `GET https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&key={api_key}`.

Returns:
- `cover_url`: extracted from `volumeInfo.imageLinks.thumbnail` (upgraded to https)
- `description`: extracted from `volumeInfo.description`

Handles:
- Empty responses (no match) → return None
- 429 rate limit → raise a retryable error with Retry-After
- Other HTTP errors → log and return None

#### 3. Worker (`app/workers/enrichment/google_books_worker.py`)

Follows the same asyncio-loop pattern as existing workers.

**Each cycle:**

1. **Query** books needing enrichment:
   ```sql
   SELECT * FROM books
   WHERE isbn IS NOT NULL
     AND array_length(isbn, 1) > 0
     AND (cover_url IS NULL OR description IS NULL)
   ORDER BY metadata_synced_at ASC NULLS FIRST
   LIMIT {batch_size}
   ```
   `NULLS FIRST` ensures oldest/never-processed books are picked first.

2. **Pick one ISBN** per book:
   - Strip hyphens and spaces
   - Prefer the longest candidate (ISBN-13)
   - Fall back to `isbn[0]`

3. **Call Google Books API**, update the `Book` row:
   ```
   book.cover_url = result.cover_url
   book.description = result.description
   book.metadata_synced_at = datetime.now(timezone.utc)
   ```

4. **Rate limiting**: If a 429 is received, stop the cycle early and wait until the next scheduled run (the backoff is built into the scan interval).

**Error handling per book:** Log the failure and continue to the next book. One bad ISBN should not block the batch.

#### 4. Startup (`app/main.py`)

Start the worker in the `lifespan` handler **regardless of `SEED_DATA`** — it only needs the database, not Koha:

```
enrichment_worker = GoogleBooksWorker()
enrichment_task = asyncio.create_task(enrichment_worker.run(), name="google-books-worker")
tasks.append(enrichment_task)
```

Shutdown: cancelled alongside other tasks in the `finally` block.

---

### ISBN Selection Strategy

| Priority | Rule |
|----------|------|
| 1 | Strip hyphens and whitespace from all candidates |
| 2 | Prefer the longest numeric string (ISBN-13 is 13 digits, ISBN-10 is 10 digits) |
| 3 | If tied, prefer the first one in the array |
| 4 | Skip candidates that are too short (< 10 digits after stripping) |

---

### Key Decisions

| Concern | Decision |
|---------|----------|
| Queue vs Scan | **Scan** — simpler, no new table, auto-backfills, resilient to downtime |
| Hook into metadata worker | **No** — the scan naturally picks up books once ISBN is populated |
| Re-fetch policy | Skip if both `cover_url` and `description` are already set |
| Rate limits | Respect 429s; free quota is 1000 requests/day — stay within it via batch size + delay |
| New DB table | **None needed** |
| Migration | **None needed** |
| Existing worker changes | **None** |
| Startup dependency | Only needs DB (not Koha), so runs even when `SEED_DATA=False` |

---

### What It Does NOT Handle

- **Real-time enrichment**: Books are enriched within one scan cycle (~60s) after their ISBN is populated. This is acceptable since cover/description are not time-critical.
- **On-demand refresh triggers**: Not needed — Google data rarely changes. If a re-fetch is needed, clear the `cover_url`/`description` on the book row and the worker will pick it up.
- **Multiple Google Books matches**: Takes the first result. In practice, ISBN lookup is unique.
