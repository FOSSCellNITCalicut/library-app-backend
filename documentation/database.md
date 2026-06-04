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