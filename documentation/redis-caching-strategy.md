# Redis Caching Strategy for NITC Library Mobile Application

## 1. Introduction

The NITC Library Mobile Application uses Redis as an in-memory cache to improve response times and reduce PostgreSQL load during peak usage. It follows a **cache-aside pattern**, where Redis is checked first and PostgreSQL is queried on cache miss. PostgreSQL serves as the system of record for the application layer, maintaining a continuously synchronized projection of Koha via background workers, while Koha remains the upstream source system accessed only through those workers.

### Architecture Principles

- **PostgreSQL** is the primary application data store. All request-time reads are served from PostgreSQL.
- **Redis** is a performance cache over PostgreSQL. It is never used for correctness decisions or freshness evaluation. Cached data may be stale at any time.
- **Koha** is not part of request-time flows. It is accessed only by background sync workers, with one exception: the user-initiated "Check Live Availability" action.
- **TTL** is used only for cache eviction and fallback expiration.

---

### 1.1 Current NITC Library Scale

The Redis caching strategy is designed to support the scale of the NIT Calicut Central Library and its growing digital services.

#### Library Statistics

| Metric | Value |
|---|---|
| Physical Books | 135,069 |
| e-Books | 11,153 |
| e-Journals | 13,150 |
| PhD Theses | 1,317 |
| Databases | 6 |
| Registered Users | 8,000+ |
| Reading Capacity | 500+ |

#### Expected Mobile Application Usage

| Metric | Estimated Value |
|---|---|
| Active Users per Day | 1,500–3,000 |
| Peak Concurrent Users | 200–500 |
| Search Requests per Day | 5,000–15,000 |
| Book Detail Requests per Day | 3,000–10,000 |
| Dashboard Requests per Day | 2,000–5,000 |

Given the large collection size and user base, repeated requests for popular books, browse feeds, and dashboard information can generate significant load on PostgreSQL. Redis is introduced to reduce repeated database access, improve response times, and increase scalability during peak usage periods such as examinations and registration periods.

---

## 2. Current Scope (Phase 1)

### 2.1 Data to be Cached

| Data | Purpose |
|---|---|
| Book Metadata | Reduce repeated book detail requests |
| Book Availability | Fast availability lookups; PostgreSQL `last_availability_sync` is the freshness authority |
| Browse Feed Pages | Faster paginated catalog loading |
| User Events | Fast dashboard loading (borrowed, fines, dues) |
| User Sessions | Fast authentication |
| Search Counters | Short-term analytics aggregation before PostgreSQL flush |
| Rate Limiting Data | Prevent API abuse |

> **Note:** Book metadata and availability are stored in separate keys owned by separate sync workers. Metadata changes infrequently; availability changes on every borrow or return. Separating them prevents high-frequency availability updates from causing unnecessary metadata cache churn.

> **Note:** Search is handled directly by PostgreSQL FTS using `tsvector` and `to_tsquery`. Search results are not cached in Redis due to high query cardinality, low reuse, and invalidation complexity. Autocomplete is also handled by PostgreSQL FTS natively.

> **Note:** New arrivals are not cached separately. They are served through the paginated browse feed (`books:browse:page:{page}`), avoiding two overlapping cache layers.

---

### 2.2 Redis Key Structure

#### Books

```
book:detail:{biblio_id}
books:availability:{biblio_id}
books:browse:page:{page}
```

**Examples:**
```
book:detail:74489
books:availability:74489
books:browse:page:1
```

`book:detail:*` contains:
- Title
- Author
- ISBN
- Publisher
- Subjects
- Description
- Cover URL

`books:availability:*` contains:
- Available copies
- Total copies
- Branch information

#### User Data

```
user:{roll_no}:events
```

**Example:**
```
user:B210234CS:events
```

`user:*:events` contains:
- Borrowed books
- Due dates
- Fines

#### Authentication

```
user:session:{token}
```

#### Analytics

```
search:count:{query}
```

**Example:**
```
search:count:data_structures
```

`search:count:*` is a short-term aggregation counter only. Values are periodically flushed to PostgreSQL for long-term analytics, trend tracking, and hot/cold book detection. Redis counters do not survive restarts and should not be treated as the source of truth for analytics.

#### Rate Limiting

```
rate:limit:{roll_no}:search
```

---

### 2.3 TTL Strategy

| Key | TTL |
|---|---|
| `book:detail:*` | 7 days |
| `books:availability:*` | 120 seconds |
| `books:browse:page:*` | 5 minutes |
| `user:*:events` | 30 minutes |
| `user:session:*` | 24 hours |
| `search:count:*` | 1 hour |
| `rate:limit:*` | 1 minute |

#### TTL Design Principles

- Primary freshness is maintained through **event-driven invalidation** by background sync workers. TTL is a safety net only, ensuring stale entries are eventually evicted if an invalidation event is missed.
- `book:detail:*` uses a long TTL because metadata changes infrequently and the Metadata Sync Worker invalidates immediately on updates.
- `books:availability:*` uses 120 seconds as a cache eviction safety net. Actual availability freshness is determined by `last_availability_sync` in PostgreSQL `books_copies`.
- `books:browse:page:*` uses a short TTL because feed composition shifts as new books are added.
- `user:*:events` uses 30 minutes because user data changes infrequently in normal usage; event-driven invalidation handles the cases when it does.
- `search:count:*` uses 1 hour as a flush interval before being persisted to PostgreSQL.

---

### 2.4 Cache Invalidation Strategy

#### Primary: Event-Driven Invalidation

Invalidation is triggered immediately by background sync workers after every update. This is the primary freshness mechanism. Each worker only invalidates the data it owns.

**Metadata Sync Worker Updates a Book** — Delete:
```
book:detail:{biblio_id}
```

**Availability Sync Worker Updates a Book** — Delete:
```
books:availability:{biblio_id}
```

**New Book Discovered by Availability Sync Worker** — Delete:
```
books:browse:page:1
```

Only page 1 is invalidated since new books appear at the top of the feed. Remaining pages rely on the existing 5-minute TTL. Global invalidation of all browse pages is avoided to prevent unnecessary cache rebuilding.

**User Event Written to PostgreSQL** — Delete:
```
user:{roll_no}:events
```

**User Logout** — Delete:
```
user:session:{token}
```

#### Secondary: Automatic TTL Expiration

TTL serves as a fallback safety net in case an invalidation event is missed. It ensures no entry remains stale indefinitely.

#### Freshness Ownership

| Cache Key | Owner | Freshness Authority | TTL Role |
|---|---|---|---|
| `book:detail:*` | Metadata Sync Worker | Event-driven invalidation | 7-day safety net |
| `books:availability:*` | Availability Sync Worker | PostgreSQL `last_availability_sync` | 120s safety net |
| `books:browse:page:*` | Availability Sync Worker | Page 1 invalidation on new book | 5-min safety net |
| `user:*:events` | User Event Writer | Event-driven invalidation | 30-min safety net |
| `user:session:*` | Auth Service | Explicit deletion on logout | 24-hr safety net |

---

### 2.5 Cache Hit / Miss Flow

All cache misses fall through to PostgreSQL, never directly to Koha — except for the explicit "Check Live Availability" action.

#### Book Detail Request

1. Student opens a book page.
2. Perform independent Redis lookups for metadata and availability:
   - `book:detail:{biblio_id}`
   - `books:availability:{biblio_id}`
3. **If both cache hit:** Return combined metadata and availability.
4. **If either cache miss:**
   - Query PostgreSQL `books` table for metadata.
   - Query PostgreSQL `books_copies` table for availability.
   - Cache each result under its respective key.
   - Return combined result.

#### Cache Stampede Protection

Under peak load, a popular book page expiring can cause many concurrent requests to hit PostgreSQL simultaneously. To prevent this:

- Use a Redis lock (`SET NX` with short expiry) when a cache miss is detected.
- Only one request acquires the lock and populates the cache.
- Other concurrent requests wait briefly and then read from the newly populated cache.

This applies especially to hot keys: `book:detail:*` and `books:availability:*`. Stampede protection is applied only for high-frequency keys during TTL expiry events.

#### Check Live Availability

If the user explicitly requests a live availability check:

1. Query PostgreSQL `books_copies` for `last_availability_sync` timestamp.
2. **If `last_availability_sync` is older than 120 seconds:**
   - Query Koha API directly for current item status.
   - Update PostgreSQL `books_copies` with fresh data and new `last_availability_sync` timestamp.
   - Invalidate `books:availability:{biblio_id}` in Redis.
   - Cache updated availability in Redis.
   - Return fresh result.
3. **If `last_availability_sync` is within 120 seconds:**
   - Return current PostgreSQL availability as sufficiently fresh.
   - Repopulate Redis cache if it was missing.

Freshness is determined by reading `last_availability_sync` from PostgreSQL, not from Redis TTL state. Redis is bypassed entirely for the freshness decision. This is the only request-time path that touches Koha, and it is user-initiated and explicit, not automatic.

#### Sync vs Live Check Distinction

| Type | Mechanism | Freshness Level | Koha Access |
|---|---|---|---|
| Background Availability Sync | Rolling worker, continuous | Approximate (~30 min cycle) | Via sync worker only |
| Check Live Availability | User-initiated, on demand | Exact (< 120 seconds) | Direct, at request time |

Background sync provides broad approximate freshness for general browsing. The live check provides exact freshness when a student needs to know right now whether a book is available.

#### Browse Feed Request

1. Check Redis: `books:browse:page:{page}`
2. **If cache hit:** Return cached page.
3. **If cache miss:**
   - Query PostgreSQL `books` table.
   - Cache result for 5 minutes.
   - Return result.

#### Search Request

Search does not use Redis caching.

1. Student enters search query.
2. Normalize query (lowercase, trim whitespace).
3. Query PostgreSQL FTS directly.
4. Return results.

Search queries have high cardinality and low reuse. PostgreSQL FTS with proper indexing is fast enough that a Redis caching layer adds complexity without meaningful gain.

#### Dashboard Request

1. Check Redis: `user:{roll_no}:events`
2. **If cache hit:** Return dashboard instantly.
3. **If cache miss:**
   - Query PostgreSQL `events` table.
   - Cache result for 30 minutes.
   - Return response.

#### Authentication Request

1. Check Redis: `user:session:{token}`
2. **If cache hit:** User is authenticated.
3. **If cache miss:**
   - Validate token with backend authentication service.
   - If valid, recreate Redis session entry.
   - Otherwise return `401 Unauthorized`.

---

### 2.5.1 Fallback and Failure Handling Strategy

#### Cache Miss Handling

When a requested key is not found in Redis:
1. Query PostgreSQL.
2. Return the response to the client.
3. Store the response in Redis using the configured TTL.

#### Redis Unavailability

If Redis becomes temporarily unavailable:
1. Skip cache lookup.
2. Query PostgreSQL directly.
3. Return the response.
4. Continue application operation without caching.

#### Session Validation Fallback

1. Check Redis session cache.
2. If found, authenticate user.
3. Otherwise validate token with backend authentication service.
4. Recreate Redis session if valid.
5. Return `401` if invalid.

#### Graceful Degradation

If Redis is unavailable:
- Search remains fully operational via PostgreSQL FTS.
- Book metadata and availability retrieval remain operational.
- Browse feed remains operational.
- Dashboard remains operational.
- Authentication remains operational through backend validation.
- Only response times may increase until Redis recovers.

#### Circuit Breaker Protection

1. Detect consecutive Redis connection failures.
2. Temporarily bypass Redis operations.
3. Retry Redis connectivity after a cooldown period.
4. Automatically resume caching once Redis becomes available.

---

### 2.6 Performance Expectations

| Operation | Without Cache | With Cache |
|---|---|---|
| Book Details | 20–80 ms | 5–30 ms |
| Availability | 20–50 ms | <10 ms |
| Browse Feed | 50–100 ms | 10–30 ms |
| Search | 50–150 ms | 50–150 ms |
| Dashboard Data | 20–60 ms | 10–30 ms |
| Session Validation | 50–100 ms | <10 ms |

Search performance is unchanged since it bypasses Redis and hits PostgreSQL FTS directly.

#### Expected Cache Hit Rates

| Cache Type | Expected Hit Rate |
|---|---|
| Book Metadata | 85–90% |
| Book Availability | 80–85% |
| Browse Feed | 90%+ |
| User Events | 75–85% |
| Session Tokens | 99% |

#### Expected Impact

- Significant reduction in PostgreSQL read load for book details, browse, and dashboard.
- Near-instant responses for frequently accessed book pages and browse feeds.
- Stable dashboard performance even during peak periods.
- Koha completely isolated from request-time load except for explicit live availability checks.

---

### 2.7 Redis Capacity Planning

#### Estimated Memory Usage

| Cache Type | Estimated Entries | Average Size | Estimated Memory |
|---|---|---|---|
| Book Metadata | 20,000 | 2 KB | 40 MB |
| Book Availability | 20,000 | 200 B | 4 MB |
| Browse Feed Pages | 50 | 10 KB | 0.5 MB |
| User Events | 3,000 | 2 KB | 6 MB |
| User Sessions | 5,000 | 500 B | 2.5 MB |
| Search Counters | 5,000 | 200 B | 1 MB |
| Rate Limiting | 5,000 | 200 B | 1 MB |

**Total Estimated Working Set: ~55–100 MB**

A Redis instance with 512 MB RAM is sufficient while leaving significant headroom for future features.

---

### 2.8 Cache Warming Strategy

Cache warming focuses on browse feeds and popular book details since search no longer uses Redis.

#### Process

1. On application startup, retrieve the top accessed `biblio_id`s and browse pages from PostgreSQL analytics.
2. Query PostgreSQL for browse feed pages 1–5.
3. Query PostgreSQL for top 500 most accessed book metadata and availability entries.
4. Store results in Redis under their respective keys.
5. Serve future requests from cache immediately.

#### Benefits

- Eliminates cold-start latency for the most accessed content.
- Browse feed is immediately fast for the first users after deployment or restart.
- Popular book pages are served from cache from startup.

#### Analytics Persistence

`search:count:*` counters in Redis are flushed to PostgreSQL periodically (every hour or on shutdown). PostgreSQL is the source of truth for:
- Long-term search trends
- Hot/cold book classification
- Popular book rankings
- Recommendation engine inputs

Redis counters are only used for short-term aggregation between flush intervals.

---

## 3. Future Scope (Phase 2+)

### 3.1 Department-wise Popular Books

```
popular:books:dept:{dept}
```

**Examples:**
```
popular:books:dept:cse
popular:books:dept:ece
```

**TTL:** 1 hour

**Use Cases:** Personalized recommendations, department reading trends

### 3.2 Global Popular Books

```
popular:books:global
```

**TTL:** 1 hour

**Use Cases:** Homepage recommendations, trending books section

### 3.3 Semester-wise Recommended Books

```
sem:books:{dept}:{semester}
```

**Examples:**
```
sem:books:cse:s5
sem:books:ece:s3
```

**TTL:** 30 days

**Use Cases:** Semester-specific recommendations, curriculum support

### 3.4 Reading History

```
user:{roll_no}:history
```

**TTL:** 30 days

**Use Cases:** Reading analytics, personalized recommendations, borrow history

### 3.5 Reading List / Wishlist

```
user:{roll_no}:reading_list
```

**TTL:** 7 days

**Use Cases:** Wishlist management, quick access to saved books

### 3.6 Due-Date Reminder System

```
notified:{roll_no}:{biblio_id}
```

**TTL:** 24 hours

**Use Cases:** Push notifications, email reminders, fine prevention alerts

### 3.7 Recommendation Engine

#### Potential Recommendation Models

- **Department-Based Recommendations** — Popular among CSE students
- **Semester-Based Recommendations** — Popular among Semester 5 students
- **Frequently Borrowed Together** — Books commonly borrowed by the same students
- **Faculty Recommended Books** — Books recommended by course instructors
- **Syllabus-Based Recommendations** — Books linked directly to courses and semester curriculum

All recommendation inputs (borrow counts, trends, co-borrowing patterns) are persisted in PostgreSQL. Redis serves only as a read cache for pre-computed recommendation results.

---

## 4. Conclusion

Redis will significantly improve application performance by caching frequently accessed data and reducing repeated reads from PostgreSQL.

The **Phase 1** implementation is intentionally lean:
- Search bypasses Redis entirely, relying on PostgreSQL FTS.
- Metadata and availability are stored in separate keys owned by separate sync workers, preventing unnecessary cache churn.
- Event-driven invalidation by sync workers is the primary freshness mechanism. TTL is a safety net.
- Cache stampede protection is applied to hot keys under peak load.
- Analytics are aggregated temporarily in Redis and persisted to PostgreSQL.

The **Phase 2** roadmap leverages cached data and PostgreSQL analytics for personalized recommendations, reading history, academic assistance, trending content, and enhanced user engagement, providing a richer and more responsive digital library experience for NIT Calicut students and faculty.
