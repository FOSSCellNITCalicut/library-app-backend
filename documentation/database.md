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
    authors TEXT[],
    isbn TEXT[],
    publisher TEXT,
    published_year INT,
    edition TEXT,
    
    -- Enrichment 
    description TEXT,
    cover_url TEXT,
    
    -- Category data 
    categories TEXT[],
    
    -- Lightweight precomputed aggregates
    -- (maintained by trigger on book_copies, not by the worker)
    total_copies INT DEFAULT 0,
    available_copies INT DEFAULT 0,
    lib_copies INT DEFAULT 0,
    mat_copies INT DEFAULT 0,
    
    -- Sync metadata 
    metadata_synced_at TIMESTAMPZ,
    availability_synced_at TIMESTAMPZ,
    
     -- Audit fields 
     created_at TIMESTAMPZ DEFAULT NOW(),
     updated_at TIMESTAMPZ DEFAULT NOW()
);
```

---

**2. book_copies**

Stores:
  - physical copies
  - availability state
  - branch information
  - circulation-related data

One row -> one physical copy.

```sql
CREATE TABLE book_copies (
    item_id BIGINT PRIMARY KEY,

    biblio_id BIGINT NOT NULL
        REFERENCES books(biblio_id)
        ON DELETE CASCADE,

    branch TEXT NOT NULL,
    acquisition_date TIMESTAMPZ,

    -- Display Fields
    callnumber TEXT,
    status VARCHAR(50) NOT NULL,

    -- Audit Fields
    updated_at TIMESTAMPZ DEFAULT NOW(),
    last_seen_at TIMESTAMPZ DEFAULT NOW()
);
```

The availability sync worker only upserts seen items, so rows for copies that have been permanently deleted from Koha would never be updated. Such ghost inventory can be cleaned up using `last_seen_at`:

```sql
DELETE FROM book_copies
WHERE last_seen_at < NOW() - INTERVAL '30 days'
```

---

**3. metadata_queue**

DB-backed queue for the metadata worker. The availability worker enqueues rows here for every newly discovered biblio. The metadata worker claims the highest-priority eligible row, processes it, then either marks it `completed` or schedules a retry.

```sql
CREATE TABLE metadata_queue (
    id BIGSERIAL PRIMARY KEY,
    biblio_id BIGINT UNIQUE NOT NULL,
    priority INT DEFAULT 0,
    retry_count INT DEFAULT 0,
    status TEXT DEFAULT 'pending',  -- 'pending' | 'completed' | 'failed'
    available_at TIMESTAMPTZ DEFAULT NOW()
);
```

`status` semantics:
- `pending`: eligible to be claimed when `available_at <= NOW()`.
- `completed`: previously succeeded. Will be flipped back to `pending` if re-enqueued (stale-data re-fetch).
- `failed`: dead-lettered after `MAX_METADATA_RETRIES` failures. Never resurrected.

Failure details (the exception repr) are logged at `WARNING` (retry) or `ERROR` (dead-letter) but are **not persisted** on the row. Inspect the worker logs to see why a row was dead-lettered.

The `enqueue_metadata_job` upsert enforces the no-resurrect contract via a `CASE` expression on conflict:
- `completed → pending` (re-fetch stale data)
- `pending → pending` (idempotent)
- `failed → failed` (dead-lettered rows stay dead; `priority` is still bumped, harmlessly)

---

**4. sync_state**

Singleton row holding the availability worker's page cursor and heartbeat. One row, ever, with `id = 1`.

```sql
CREATE TABLE sync_state (
    id INT PRIMARY KEY DEFAULT 1,
    current_page INT NOT NULL DEFAULT 1,
    last_completed_at TIMESTAMPTZ  -- heartbeat; NULL until first successful page
);
```

The metadata worker does not use this table — it gets its work from `metadata_queue`. The `last_completed_at` column is written by the availability worker at three sites (successful page, page wrap-around, post-backoff page advance) and **is the producer side of a heartbeat**. The consumer side is not implemented: nothing in the running app currently reads `last_completed_at` to detect a stuck worker, and `/health` does not check it. If the worker dies, the timestamp simply stops updating. Alerting is TODO — see `documentation/issues.md` ("Sync worker dies silently").

---

## Aggregate trigger (implemented)

The aggregates on `books` are maintained by a Postgres trigger on `book_copies`. The worker does not write them.

```sql
CREATE OR REPLACE FUNCTION recompute_book_aggregates() RETURNS TRIGGER AS $$
DECLARE
    affected_biblio_id BIGINT;
BEGIN
    affected_biblio_id := COALESCE(NEW.biblio_id, OLD.biblio_id);

    UPDATE books SET
        total_copies = agg.total,
        available_copies = agg.available,
        lib_copies = agg.lib,
        mat_copies = agg.mat,
        availability_synced_at = NOW()
    FROM (
        SELECT
            COUNT(*)::INT AS total,
            COUNT(*) FILTER (WHERE status = 'Available')::INT AS available,
            COUNT(*) FILTER (WHERE branch = 'LIB')::INT AS lib,
            COUNT(*) FILTER (WHERE branch = 'MAT')::INT AS mat
        FROM book_copies
        WHERE biblio_id = affected_biblio_id
    ) AS agg
    WHERE books.biblio_id = affected_biblio_id;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER book_copies_aggregates
AFTER INSERT OR UPDATE OR DELETE ON book_copies
FOR EACH ROW EXECUTE FUNCTION recompute_book_aggregates();
```

Branch codes are hardcoded for now (`'LIB'` and `'MAT'`). If NITC adds new branches, this trigger needs a migration to update the `FILTER` clauses, or a `library_branches` lookup table should be introduced.
