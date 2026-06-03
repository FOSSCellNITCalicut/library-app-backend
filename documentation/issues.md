# NITC Library App - Known Issues & Proposed Solutions

---

## Bottlenecks

### No full-text search index - Critical
`LIKE '%python%'` queries do full table scans. Slow as the DB grows to tens of thousands of books.

**Solution:** Add a `tsvector` column, populate via trigger, and index it with GIN. PostgreSQL full-text search is fast and built-in - no extra service needed. Must be explicitly defined in the schema before launch.

---

### Metadata queue grows unbounded - Medium
If the metadata sync worker falls behind (Koha slowness, rate limiting, restarts), the metadata_queue table grows large, causing slow queue reads and delayed visibility for new books.

**Solution:** Add a queue depth metric. Alert if queue exceeds a threshold (e.g. 500 pending jobs). Separate high-priority (newly discovered biblios) from low-priority (rolling refresh) jobs in the queue so new books are always visible fast.

---

### Redis serving stale data after sync - Medium
After the sync worker updates a book's metadata or availability in Postgres, the Redis cache still holds the old value until TTL expires. Users get outdated data even though the DB is fresh.

**Solution:** On every sync upsert, explicitly invalidate the Redis key for that biblio_id. Do not rely solely on TTL expiry for correctness.

---

## Failure Scenarios

### Sync worker dies silently - Critical
If the availability or metadata sync worker crashes, the DB goes stale with no visible error. Users see outdated data and nobody knows.

**Solution:** Each worker must write a heartbeat to sync_state after every page. A watchdog cron checks if last_completed_at is older than a threshold (10 mins for availability, 1 hour for metadata) and alerts via email or Telegram.

---

### /items endpoint schema changes - Critical
If Koha updates and renames or removes fields in the /items response (e.g. checked_out_date, not_for_loan_status), the availability sync worker silently miscomputes availability for every book. No errors thrown, just wrong data.

**Solution:** Validate the first page of /items response fields before each sync run. Assert expected fields exist. Alert and halt sync if validation fails rather than writing corrupt data to the DB.

---

### DB trigger fails silently - Critical
The architecture relies on DB-level triggers to keep total_copies and available_copies on the books table consistent with books_copies. If the trigger breaks or is accidentally dropped, aggregates go out of sync with no obvious symptom.

**Solution:** Add a periodic consistency check - compare SUM of books_copies per biblio_id against books.total_copies and books.available_copies. Alert on any mismatch. Run this check after every deployment.

---

### Bootstrap interrupted midway - Medium
The initial sync pages through all /items and enqueues metadata for every discovered biblio. If the process is interrupted (crash, network failure, restart), partial data is served - some books exist with no metadata, others are missing entirely.

**Solution:** sync_state table handles resumability - worker picks up from current_page on restart. Placeholder books rows inserted during discovery must be clearly marked (e.g. metadata_synced_at IS NULL) so the API never returns them to the frontend until metadata is populated.

---

### Ghost inventory - Medium
When a physical copy is permanently deleted from Koha, the sync worker never sees it again - it just stops appearing in /items pages. The books_copies row stays forever, inflating available_copies and total_copies.

**Solution:** Use last_seen_at on books_copies. Any row not updated in 30 days is considered a ghost and deleted. Run cleanup as a scheduled job, not inline during sync.

---

### Google Books enrichment rate limited - Medium
If Google Books enrichment runs too aggressively during bootstrap or rolling refresh, Google will rate limit or block the server IP. Cover URLs will be missing for large portions of the catalog.

**Solution:** Treat enrichment as strictly best-effort. Run it at low speed with 200-300ms delay between requests and exponential backoff on 429s. Never block metadata insertion waiting for enrichment to complete.

---

### On-demand live availability check hangs - Medium
The "Check Live Availability" button on the book detail page hits Koha directly. If Koha is slow or down, the button appears frozen and the user waits indefinitely.

**Solution:** Hard 3s timeout on all live Koha calls. On timeout, return cached availability with a stale flag and show "last updated X mins ago" instead of hanging or showing an error.

---

### Stale availability data - Low
With 30 min rolling sync, a book shown as available could have been borrowed recently.

**Solution:** Show "as of X mins ago" on the UI next to availability. The on-demand live check button handles cases where exact availability matters. Accepted tradeoff given low borrowing frequency at a college library.

---

## Scalability Concerns

### OPAC rate limiting during initial sync - Medium
During bootstrap, the backend pages through all /items and fetches MARC for every new biblio_id. Without throttling this could get the server IP blocked by NITC.

**Solution:** Rolling sync with sleep(10) between pages. For MARC fetches, 100-200ms delay between requests. Bootstrap must run over hours, not minutes. Never parallelise Koha requests.

---

### Hot/cold book sync inefficiency - Low (for now)
Rolling sync treats all books equally. A book last borrowed in 2009 gets the same availability sync frequency as one borrowed yesterday.

**Solution:** Track borrowing recency and split into hot and cold tiers. Hot books get more frequent syncs, cold books much less. Implement after launch once borrowing data is available.

---

### DB size over time - Low (for now)
60k+ books with metadata and copies is well under 500MB. Risk grows only if availability history or event logs accumulate without cleanup.

**Solution:** Never store availability history - only the latest snapshot per item in books_copies. Define a retention policy for the events table before implementing it.

---

## Security Risks

### Backend is a public proxy - Security
Anyone who finds the API can trigger Koha requests through the backend, potentially getting the server IP rate-limited or blocked by NITC.

**Solution:** API key auth as middleware across all endpoints. A simple shared secret in the app is enough to stop casual abuse without needing user accounts.

---

### No input sanitisation on search - Security
Search query goes directly into a PostgreSQL FTS query. Unsanitised input can cause unexpected query behaviour or expose internal errors.

**Solution:** Always use parameterised queries. Sanitise and length-limit search input. Reject or strip special characters that have no place in a book search query.

---

## Monitoring Requirements

### Sync worker heartbeat
If a worker dies, nothing breaks visibly - data just goes stale. Need proactive detection, not user complaints.

**Solution:** Watchdog cron checks sync_state.last_completed_at for each worker. Alert if availability worker hasn't updated in 10 mins, metadata worker in 1 hour.

---

### /items schema validation on sync start
Silent schema breakage is worse than a loud failure.

**Solution:** Validate first page of /items fields before each sync run. Log and alert on unexpected schema. Do not write to DB if validation fails.

---

### DB trigger consistency check
Triggers can break silently especially after migrations or deployments.

**Solution:** Scheduled job compares books_copies aggregates against books.total_copies and available_copies. Alert on any mismatch.

---

### Metadata queue depth
A growing queue means new books stay invisible to users longer than acceptable.

**Solution:** Expose queue depth as a metric. Alert if depth exceeds 500. Separate high and low priority lanes.

---

### Cache hit rate
If Redis hit rate drops, TTLs may be too short or cache is being invalidated too aggressively.

**Solution:** Log cache hits vs misses per endpoint. If miss rate exceeds 20%, tune TTL or invalidation logic.

---

### On-demand availability call latency
The live check hits Koha directly. If it starts timing out frequently, something is wrong with Koha or the network.

**Solution:** Track p95 latency of live availability calls. Alert if p95 exceeds 2s. Surface timeout rate as a separate metric.

---

## Not Yet Documented (acknowledged in architecture doc)

- Explicit sync failure policy and retry behaviour (exponential backoff mentioned but not detailed)
- Index strategies for books and books_copies
- Schema for events table and metadata_queue table
