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

DB-backed queue for the metadata worker. The availability worker enqueues rows here for every newly discovered biblio. The metadata worker claims them with `SELECT ... FOR UPDATE SKIP LOCKED`.

```sql
CREATE TABLE metadata_queue (
    id BIGSERIAL PRIMARY KEY,
    biblio_id BIGINT UNIQUE NOT NULL,
    priority INT DEFAULT 0,
    retry_count INT DEFAULT 0,
    status TEXT DEFAULT 'pending',  -- 'pending' | 'completed' | 'failed'
    last_error TEXT,
    available_at TIMESTAMPTZ DEFAULT NOW()
);
```

`status` semantics:
- `pending`: eligible to be claimed when `available_at <= NOW()`.
- `completed`: previously succeeded. Will be flipped back to `pending` if re-enqueued (stale-data re-fetch).
- `failed`: dead-lettered after `MAX_METADATA_RETRIES` failures. Never resurrected.

---

**4. sync_state**

Per-worker progress and heartbeat. There is one row per worker, keyed by `worker_name`.

```sql
CREATE TABLE sync_state (
    worker_name TEXT PRIMARY KEY,
    current_page INT NOT NULL DEFAULT 1,
    last_completed_at TIMESTAMPTZ,  -- heartbeat; NULL until first successful page
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

The availability worker writes `('availability', ...)`, the metadata worker is tracked with `('metadata', ...)` (page counter currently unused but reserved for a future rolling refresh loop).

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
