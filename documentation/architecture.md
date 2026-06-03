# Scalable Library App Backend Architecture

## Previously Proposed Architecture 

```
Frontend 
    ↓ 
FastAPI 
    ↓ 
Koha APIs 
    ↓ 
Google Books 
    ↓ 
Merge responses 
    ↓ 
Return frontend response
```

## Problems

### 1. Runtime N+1 Requests

**For browse feeds:**

- 1 request → items endpoint
- N requests → biblios endpoint

**Example Flow:**

`GET /items` → returns 20 item rows

**Then:** `GET /biblios/{id}` called 20 times

**Total:** 21 external requests per frontend request

---

### 2. Latency & No Independent Scaling

Every frontend request depends on:

- Koha uptime
- Koha latency
- Network stability

If Koha slows, our app will slow down. In worst case, if Koha is down, our app will never return the intended response.

---

### 3. Repeated MARC Parsing

Every request repeatedly parses MARC wasting CPU resources, increases the latency and complicates request handler functions.

---

### 4. Repeated Google Books Requests

If every request:

- fetches metadata
- then fetches Google Books

the same ISBN may be requested repeatedly.

---

### 5. Search Scalability Limitations

Search relies entirely on Koha RSS/XML search. But this will become a pain point when we want to implement typo tolerance, semantic search, rank results etc.

## New Architecture

I propose that we shift from request-time computation to a pre-computed efficient read model. 

This way Koha API can still serve as historical truth, but we no longer have to deal with the above problems by normalising the data and syncing periodically to reflect real data.

## New Request Flow

### Browse Feed

We will be going forward with a simple catalog based feed for now. Most likely a rule based catalog until we have enough data to support personalised feeds (but I’m skeptical if a library app even needs personalisation).

```
Frontend
   ↓ 
FastAPI
   ↓ 
Redis Cache Lookup (cache miss)
   ↓ 
PostgreSQL
   ↓ 
Return normalized books
```

**NO Koha calls during browse requests.**

---

### Search

```
Frontend
   ↓ 
FastAPI
   ↓ 
PostgreSQL FTS
   ↓ 
Return ranked results
```

---

### Book Details

```
Frontend
   ↓ 
FastAPI
   ↓
Redis Cache Lookup (cache miss)
   ↓
PostgreSQL
   ↓
Return complete metadata
```

---

## API Design


### Browse Books

`GET /books/browse?page=1`

Returns:

```json
{
  "items": [
    {
      "biblio_id": 897,
      "title": "Engineering Mathematics",
      "author": "Natarajan",
      "edition": "vol. 1 part 2"
      "cover_url": "...",
      "available_copies": 2,
      "total_copies": 5,
      "branches": ["LIB"]
    },
    ...
  ]
}

```

---

### Search Books

`GET /search?q=python`

---

### Book Details

`GET /books/{biblio_id}`

---

## Database Schema

**1. books**

Stores:
  - Metadata
  - Search Data

One row -> one unique book/biblio.

```sql
CREATE TABLE books ( 
    -- Koha identity 
    biblio_id BIGINT PRIMARY KEY,
    
    -- Core metadata 
    title TEXT NOT NULL,
    author TEXT,
    isbn TEXT,
    publisher TEXT,
    published_year INT,
    edition TEXT,
    
    -- Enrichment 
    description TEXT,
    cover_url TEXT,
    
    -- Category data 
    category TEXT[],
    
    -- Lightweight precomputed aggregates 
    total_copies INT DEFAULT 0,
    available_copies INT DEFAULT 0,
    lib_copies INT DEFAULT 0,
    mat_copies INT DEFAULT 0,
    
    -- Sync metadata 
    metadata_synced_at TIMESTAMP,
    availability_synced_at TIMESTAMP,
    
     -- Audit fields 
     created_at TIMESTAMP DEFAULT NOW(),
     updated_at TIMESTAMP DEFAULT NOW()
);
```

---

**2. books_copies**

Stores:
  - physical copies
  - availability state
  - branch information
  - circulation-related data

One row -> one physical copy.

```sql
CREATE TABLE books_copies (
    item_id BIGINT PRIMARY KEY,

    biblio_id BIGINT NOT NULL
        REFERENCES books(biblio_id)
        ON DELETE CASCADE,

    branch TEXT NOT NULL,
    acquisition_date TIMESTAMP, -- Debatable field

    -- Display Fields
    callnumber TEXT,
    available BOOLEAN NOT NULL DEFAULT TRUE,

    -- Audit Fields
    updated_at TIMESTAMP DEFAULT NOW(),
	last_seen_at TIMESTAMP DEFAULT NOW()
);
```

Since the current background sync logic, only upserts seen items, there arises an issue with ghost inventory. In case a particular book copy is permanently deleted from Koha, we can utilise the `last_seen_at` for cleaning up such records.

```sql
DELETE FROM books_copies
WHERE last_seen_at < NOW() - INTERVAL '30 days'
```

> [!IMPORTANT]
> Add a DB level trigger `available_copies` and `total_copies` on `books` table always consistent with books_copies. No manual aggregation step needed in the sync worker, no race conditions from concurrent upserts.

---

## Background Sync

The most important architectural change in the new design is:
- moving expensive work away from request-time
- into background synchronization jobs

Instead of:
```
Frontend Request
    ↓
Koha APIs
    ↓
MARC parsing
    ↓
Google Books
    ↓
Aggregation
    ↓
Response
```

on every request,

we do:

```
Background Workers
    ↓
Fetch + normalize data
    ↓
Store locally
```

ONCE.

Then frontend requests become:
- fast
- cacheable
- independent of Koha latency

---

### Important:

We won’t be hammering Koha API will say 200-300 API requests in a second, instead we will be utilising a rolling sync.

```python
while True:
    sync_next_page()
    await sleep(10)
```

This facilitates easier retries, better Koha friendliness and also removes the need for gathering networking requests.

This also requires the need for maintaining a separate `sync_state` table, in case of failures, system restarts, network error etc. 
```sql
CREATE TABLE sync_state (
    worker_name TEXT PRIMARY KEY,
    current_page INT NOT NULL,
    last_completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

### 1. Metadata Sync Worker

#### Purpose

Synchronize:

- titles
- authors
- ISBNs
- publishers
- descriptions
- categories
- year
- edition
- cover

into the `books` table.

We’ll be implementing a 3 layer metadata fetching strategy:

1. When `/items` discovers a new biblio_id: enqueue metadata fetching. This is mandatory as it populates the entire catalog.
2. **Rolling Metadata Refresh**
    - Run continuously at LOW speed.
    - For example, around 1000 biblios/day This is perfectly reasonable. Even, 50k books are refreshed every <= 50 days
4. **On-Demand Stale Refresh**
    - Book opened or searched will check the `last_metadata_sync < NOW() - INTERVAL 'X days'`. If stale, enqueue background refresh. But this should still return cached data immediately.

Before enqueueing metadata refresh, the worker must verify that no active refresh job already exists for the same `biblio_id`.

---

### 2. Availability Sync Worker

#### Purpose

Synchronize:
- physical copies
- availability state
- branch information

into: books_copies

```
GET /items?page=N
        ↓
For each item:
    compute availability
        ↓
Upsert into books_copies
        ↓
GROUP BY biblio_id
        ↓
(trigger automatically updates books table)
```

This is better than hitting `/api/v1/public/biblios/{id}/items` because we will introduce N+1 during syncing itself.

Along with this feature, we will be having a "Check Live Availability" button in the `books-id` page which indicates that the backend should directly hit Koha if the current availability in DB was updated greater than 120 seconds ago, update the DB cache, and returns a fresh result.

This allows background availability synchronization to prioritize broad approximate freshness, while exact availability can be verified on demand. So even 30 mins is enough for general browsing/search. 

We must identify the perfect `items_per_page` number for the `/items` Koha API which returns the optimal number of books with a quick response time.

---

### New Book Discovery

The availability sync worker acts as the primary discovery mechanism for newly added biblios.

When unseen `biblio_id`s are detected:

- a placeholder `books` row is inserted immediately
- metadata sync is enqueued with HIGH priority
- search indexing occurs after metadata normalisation

This guarantees rapid visibility for newly added books while preserving rolling synchronisation behaviour.

---

## Note:

- We will also be having another table for viewing historical events for every user like fines, holds, renews etc. Rechecking this every time when the user logs in will most likely introduce latency for the user to hit the Koha APIs. Moreover Koha User APIs are HTML-based which makes scraping expensive. 

- We can instead store the events in our DB as a separate `events` table, so retrieval is much easier.

- All writes will be happening through the Koha API, but every read will happen from our PostgreSQL DB. This also allows room for Redis caching.

- Schema for the **events** and **metadata_queue** table will be **updated later**. Reason for defaulting to DB level `metadata_queue` and `sync_state` tables are that the DB queue won’t really be a bottleneck. 

- Another optimisation will be separating the "Hot" & "Cold" Books. We can track what books are being recently borrowed, dormant books etc. This way we can have different availability sync frequency for them increasing efficiency.

- **Rate Limiting** is implied as a middleware to be established across all endpoints.

- An explicit **Sync Failure Policy** and **Index Strategies** should be added to the documentation soon.

- Retries must use exponential backoff.

---

## Initial DB Sync

The very first synchronization of the database will be different from the normal rolling synchronization process because the local PostgreSQL database initially contains no records.

This initial sync is effectively a one-time bootstrap process whose purpose is to populate:

- books
- books_copies
- search indexes
- metadata caches

from the Koha APIs.

Although the bootstrap process may take longer to complete, this ensures:

- predictable Koha load
- operational consistency
- simpler retry semantics
- easier observability
- lower infrastructure complexity

---

### Goals

The initial sync must:

- populate the entire catalog
- avoid overwhelming Koha
- support resumability in case of failures
- avoid duplicate inserts
- establish initial aggregate counts
- initialize metadata enrichment pipelines

---

### Initial Availability Bootstrap:

The first phase of the bootstrap process will focus on the /items endpoint because it provides:

- all physical copies
- biblio_id
- branch information
- availability

This allows us to:

- populate books_copies
- discover all existing biblios

without introducing N+1 sync behavior.

**Flow:**

```
GET /items?_page=N&_per_page=LIMIT
        ↓
Upsert books_copies
        ↓
Extract unique biblio_ids
        ↓
Insert unknown biblios into metadata queue
        ↓
Continue until all pages exhausted
```

---

### Metadata Bootstrap

Once biblios are discovered from /items, metadata workers will begin fetching:

/api/v1/public/biblios/{id}

for only unknown biblios.

The metadata bootstrap worker will then:

- parse MARC
- normalize fields
- populate the books table
- initialize search indexes
- trigger Google Books enrichment

---

### Google Books Enrichment

Google Books enrichment will happen asynchronously after metadata insertion. Mostly will only be used for book cover URLs.

This avoids:

- slowing initial sync
- blocking metadata ingestion
- unnecessary API contention

Enrichment should be treated as best-effort enhancement, not critical sync infrastructure.

This must also use a rolling request to avoid getting rate limited by Google.
