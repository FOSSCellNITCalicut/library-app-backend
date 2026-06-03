# NITC Library App - Known Issues & Proposed Solutions

---

## Bottlenecks

### N+1 query on browse/search page - Critical
Browse returns 20 rows from books_copies, then fires 20 separate DB queries to fetch each book's metadata. Slow and wasteful.

**Solution:** Use `WHERE biblio_id = ANY($1)` with an array - single query fetches all rows at once. Always batch. DB-level triggers on books_copies keep total_copies and available_copies on the books table always up to date, removing the need for any aggregation at request time.

---

### No full-text search index - Medium
`LIKE '%python%'` queries do full table scans. Slow as the DB grows to tens of thousands of books.

**Solution:** Add a `tsvector` column, populate via trigger, and index it with GIN. PostgreSQL full-text search is fast and built-in - no extra service needed. Must be explicitly defined in the schema before launch.

---

## Failure Scenarios

### OPAC goes down - Low (now)
Browse and search no longer depend on Koha uptime. The only live Koha call remaining is the on-demand "Check Live Availability" button on the book detail page.

**Solution:** If the live availability call fails or times out, fall back to the cached DB value and show "as of X mins ago". Never error out the page entirely.

---

### Sync worker dies silently - Critical
If the availability or metadata sync worker crashes, the DB goes stale with no visible error. Users see outdated data and nobody knows.

**Solution:** Each worker must write a heartbeat to the sync_state table after every page. A separate watchdog cron job checks if last_completed_at is older than a threshold (e.g. 10 mins for availability, 1 hour for metadata) and alerts via email or Telegram bot.

---

### /items endpoint schema changes - Medium
If Koha updates and renames or removes fields in the /items response (e.g. checked_out_date, not_for_loan_status), the availability sync worker silently miscomputes availability for every book.

**Solution:** Add a schema validation step at the start of each sync run. Assert expected fields exist in the first page response. Alert and halt sync if validation fails rather than writing corrupt data.

---

### Stale availability data - Low
With 30 min rolling sync, a book shown as "available" could have been borrowed recently.

**Solution:** Show "as of X mins ago" next to availability on the UI. The on-demand live check button on the book detail page handles cases where exact availability matters.

---

### Metadata queue grows unbounded - Medium
If the metadata sync worker falls behind (Koha slowness, rate limiting, restarts), the metadata_queue table can grow large, causing slow queue reads and delayed visibility for new books.

**Solution:** Add a queue depth metric. Alert if queue exceeds a threshold (e.g. 500 pending jobs). Separate high-priority (newly discovered biblios) from low-priority (rolling refresh) jobs in the queue.

---

## Scalability Concerns

### OPAC rate limiting during initial sync - Medium
During the bootstrap phase, the backend pages through all /items and then fetches MARC for every new biblio_id. Without throttling this could get the server IP blocked.

**Solution:** Rolling sync with sleep(10) between pages as defined in the architecture. For MARC fetches, add 100-200ms delay between requests. Bootstrap should run over hours, not minutes.

---

### DB size over time - Low (for now)
60k+ books with metadata and copies is well under 500MB. Risk grows only if availability history or event logs are stored without cleanup.

**Solution:** Never store availability history - only the latest snapshot per item in books_copies. Use last_seen_at cleanup for ghost inventory. Define a retention policy for the events table before it is implemented.

---

### Hot/cold book sync inefficiency - Low (for now)
Rolling sync treats all books equally. A book last borrowed in 2009 gets the same sync frequency as one borrowed yesterday.

**Solution:** Track borrowing recency and split books into hot and cold tiers. Hot books get more frequent availability syncs. Cold books can be refreshed much less often. Implement after launch when borrowing data is available.

---

## Security Risks

### Backend is a public proxy - Security
Anyone who finds the API can trigger Koha requests through the backend, potentially getting the server IP rate-limited or blocked by NITC.

**Solution:** Add API key auth as middleware across all endpoints. A simple shared secret in the app is enough to stop casual abuse without needing user accounts.

---

### No input sanitisation on search - Security
Search query goes directly into a PostgreSQL FTS query. Unsanitised input can cause unexpected query behaviour or expose internal errors.

**Solution:** Always use parameterised queries. Sanitise and length-limit search input before use. Reject or strip special characters that have no business being in a book search.

---

## Monitoring Requirements

### Sync worker heartbeat
If a worker dies, nothing breaks visibly - data just goes stale. Need proactive detection.

**Solution:** Watchdog cron checks sync_state.last_completed_at for each worker. Alert if availability worker hasn't updated in 10 mins, metadata worker in 1 hour.

---

### /items schema validation on sync start
Silent schema breakage is worse than a loud failure.

**Solution:** Validate first page of /items response fields before each sync run. Log and alert on unexpected schema. Do not write to DB if validation fails.

---

### Cache hit rate
If Redis cache hit rate drops, it means either the cache is too small or TTLs are too short.

**Solution:** Log cache hits vs misses per endpoint. If miss rate exceeds 20%, tune TTL or cache size accordingly.

---

### On-demand availability call latency
The live check on the book detail page hits Koha directly. If it hangs, the button appears broken.

**Solution:** Set a hard 3s timeout on all live Koha calls. Return cached availability with a stale flag on timeout instead of hanging or erroring.

---

### Metadata queue depth
A growing queue means new books are invisible to users for longer than acceptable.

**Solution:** Expose queue depth as a metric. Alert if depth exceeds 500. Separate high and low priority lanes in the queue.

---

## Not Yet Documented (acknowledged in architecture doc)

- Explicit sync failure policy and retry behaviour (exponential backoff is mentioned but not detailed)
- Index strategies for books and books_copies
- Schema for events table and metadata_queue table
- Sync Failure Policy
