# Redis Caching Strategy for NITC Library Mobile Application

## 1. Introduction

The NITC Library Mobile Application will integrate Redis as an in-memory caching layer to improve response times, reduce load on the Koha backend, and provide a smoother user experience during peak usage periods.

Redis will be used as a temporary storage layer and not as the primary source of truth. All authoritative data will remain in the Koha database. The application will follow a **Cache-Aside Pattern** where Redis is checked first, and the backend database is queried only when data is not present in cache.

---

## 1.1 Current NITC Library Scale

The Redis caching strategy is designed to support the scale of the NIT Calicut Central Library and its growing digital services.

### Library Statistics

| Metric           | Value   |
| ---------------- | ------- |
| Physical Books   | 135,069 |
| e-Books          | 11,153  |
| e-Journals       | 13,150  |
| PhD Theses       | 1,317   |
| Databases        | 6       |
| Registered Users | 8,000+  |
| Reading Capacity | 500+    |

### Expected Mobile Application Usage

| Metric                       | Estimated Value |
| ---------------------------- | --------------- |
| Active Users per Day         | 1,500–3,000     |
| Peak Concurrent Users        | 200–500         |
| Search Requests per Day      | 5,000–15,000    |
| Book Detail Requests per Day | 3,000–10,000    |
| Dashboard Requests per Day   | 2,000–5,000     |

Given the large collection size and user base, repeated requests for popular books, search queries, and dashboard information can generate significant load on the Koha backend. Redis is introduced to reduce repeated database access, improve response times, and increase scalability during peak usage periods such as examinations and registration periods.

---

# 2. Current Scope (Phase 1)

## 2.1 Data to be Cached

| Data                  | Purpose                              |
| --------------------- | ------------------------------------ |
| Search Results        | Reduce repeated search queries       |
| Search Autocomplete   | Faster search suggestions            |
| Book Metadata         | Reduce repeated book detail requests |
| New Arrivals          | Faster homepage loading              |
| User Borrowed Books   | Faster dashboard loading             |
| User Fine Information | Quick access to fines                |
| User Due Dates        | Quick access to due dates            |
| User Sessions         | Fast authentication                  |
| Search Counters       | Analytics and future recommendations |
| Rate Limiting Data    | Prevent API abuse                    |

> **Note:** Book metadata caching covers bibliographic information only (title, author, ISBN, publisher, subjects). Real-time availability and copy status are always fetched live from Koha and are never cached.

---

## 2.2 Redis Key Structure

### Search

```text
search:results:{query}
search:count:{query}
search:autocomplete:{prefix}
```

Examples:

```text
search:results:data_structures
search:count:data_structures
search:autocomplete:dat
```

### Books

```text
book:detail:{biblionumber}
```

Example:

```text
book:detail:74489
```

### Homepage

```text
new:arrivals:all
```

### User Data

```text
user:{roll_no}:borrowed
user:{roll_no}:fines
user:{roll_no}:due_dates
```

Examples:

```text
user:B210234CS:borrowed
user:B210234CS:fines
user:B210234CS:due_dates
```

### Authentication

```text
user:session:{token}
```

### Rate Limiting

```text
rate:limit:{roll_no}:search
```

---

## 2.3 TTL Strategy

| Key                   | TTL       |
| --------------------- | --------- |
| search:results:*      | 5 minutes |
| search:count:*        | 7 days    |
| search:autocomplete:* | 1 hour    |
| book:detail:*         | 7 days    |
| new:arrivals:all      | 24 hours  |
| user:*:borrowed       | 2 minutes |
| user:*:fines          | 5 minutes |
| user:*:due_dates      | 5 minutes |
| user:session:*        | 24 hours  |
| rate:limit:*          | 1 minute  |

### TTL Design Principles

* Frequently changing data uses short TTLs.
* Rarely changing metadata uses long TTLs.
* Authentication data remains cached for active sessions.
* Search analytics require longer retention periods.

---

## 2.4 Cache Invalidation Strategy

### Automatic Expiration

Most cached entries expire automatically using TTL.

### Event-Based Invalidation

#### Book Metadata Updated

Delete:

```text
book:detail:{biblionumber}
```

#### New Book Added

Delete:

```text
new:arrivals:all
```

#### Student Borrows a Book

Delete:

```text
user:{roll_no}:borrowed
user:{roll_no}:due_dates
```

#### Student Returns a Book

Delete:

```text
user:{roll_no}:borrowed
user:{roll_no}:due_dates
```

#### Student Renews a Book

Delete:

```text
user:{roll_no}:due_dates
```

#### Fine Payment

Delete:

```text
user:{roll_no}:fines
```

#### User Logout

Delete:

```text
user:session:{token}
```

---

## 2.5 Cache Hit / Miss Flow

### Search Request

1. Student enters search query.
2. Check Redis:

```text
search:results:{query}
```

3. If cache hit:

   * Return cached results.
4. If cache miss:

   * Query Koha API.
   * Store result in Redis.
   * Return result.

### Book Detail Request

1. Student opens a book page.
2. Check Redis:

```text
book:detail:{biblionumber}
```

3. If cache hit:

   * Return cached book metadata.
4. If cache miss:

   * Query Koha API.
   * Cache result for 7 days.
   * Return result.

### Dashboard Request

Check:

```text
user:{roll_no}:borrowed
user:{roll_no}:fines
user:{roll_no}:due_dates
```

* If cache hit:

  * Return dashboard instantly.
* If cache miss:

  * Query backend.
  * Cache result.
  * Return response.

### Authentication Request

Check:

```text
user:session:{token}
```

* If cache hit:

  * User is authenticated.
* If cache miss:

  * Return 401 Unauthorized.

---

## 2.5.1 Fallback and Failure Handling Strategy

Redis is used only as a performance optimization layer and not as the primary source of truth.

### Cache Miss Handling

When a requested key is not found in Redis:

1. Query the Koha backend.
2. Return the response to the client.
3. Store the response in Redis using the configured TTL.

### Redis Unavailability

If Redis becomes temporarily unavailable:

1. Skip cache lookup.
2. Query the Koha backend directly.
3. Return the response.
4. Continue application operation without caching.

### Session Validation Fallback

1. Check Redis session cache.
2. If found, authenticate user.
3. Otherwise validate token with backend.
4. Recreate Redis session if valid.
5. Return 401 if invalid.

### Graceful Degradation

If Redis is unavailable:

* Search remains operational.
* Book metadata retrieval remains operational.
* Dashboard remains operational.
* Authentication remains operational.

Only response times may increase.

### Circuit Breaker Protection

* Detect consecutive Redis failures.
* Temporarily bypass Redis.
* Retry after cooldown period.
* Resume caching automatically after recovery.

---

## 2.6 Performance Expectations

| Operation          | Without Cache | With Cache |
| ------------------ | ------------- | ---------- |
| Search Results     | 200–500 ms    | 10–50 ms   |
| Book Details       | 100–300 ms    | 5–30 ms    |
| Dashboard Data     | 100–200 ms    | 10–50 ms   |
| Autocomplete       | 50–150 ms     | <10 ms     |
| Session Validation | 50–100 ms     | <10 ms     |

### Expected Cache Hit Rates

| Cache Type          | Expected Hit Rate |
| ------------------- | ----------------- |
| Search Results      | 70–80%            |
| Book Metadata       | 85–90%            |
| Autocomplete        | 95%+              |
| User Dashboard Data | 60–70%            |
| Session Tokens      | 99%               |
| New Arrivals        | 95%+              |

### Expected Impact

* 70–90% reduction in backend read requests.
* Faster dashboard loading.
* Faster search experience.
* Reduced load on Koha servers.
* Better scalability during examination periods.
* Near-instant responses for frequently accessed data.

---

## 2.7 Redis Capacity Planning

### Estimated Memory Usage

| Cache Type                | Estimated Entries | Average Size | Estimated Memory |
| ------------------------- | ----------------- | ------------ | ---------------- |
| Search Results            | 5,000             | 5 KB         | 25 MB            |
| Book Metadata             | 20,000            | 2 KB         | 40 MB            |
| Autocomplete Data         | 2,000             | 1 KB         | 2 MB             |
| User Dashboard Data       | 3,000             | 2 KB         | 6 MB             |
| User Sessions             | 5,000             | 500 B        | 2.5 MB           |
| Analytics & Rate Limiting | 10,000            | 200 B        | 2 MB             |

**Total Estimated Working Set:** ~80–150 MB

A Redis instance with **512 MB RAM** is expected to be sufficient while leaving headroom for future features.

---

## 2.8 Search Optimization Strategy

### Query Normalization

Examples:

```text
Data Structures
data structures
data  structures
DATA STRUCTURES
```

Normalized to:

```text
data_structures
```

Benefits:

* Higher cache hit rate
* Reduced duplicate entries
* Lower Redis memory usage
* Consistent search behavior

Example key:

```text
search:results:data_structures
```

---

### Partial Query Caching

Examples:

```text
d
da
dat
data
data st
data stru
```

Cache:

```text
search:autocomplete:data
search:autocomplete:data_stru
```

Benefits:

* Faster autocomplete
* Reduced backend traffic
* Better user experience

---

### Cache Warming

#### Process

1. Retrieve top 100 search queries.
2. Query Koha at startup.
3. Store results in Redis.
4. Serve future requests from cache.

#### Example Popular Searches

* Data Structures
* Operating Systems
* Database Management Systems
* Computer Networks
* Machine Learning

#### Benefits

* Faster first-user experience
* Reduced cold-start latency
* Higher cache hit rates

### Expected Search Impact

* Increase search cache hit rate from **70–80%** to **85–95%**
* Reduce duplicate cache entries
* Improve autocomplete responsiveness
* Lower Koha search traffic during peak periods

---

# 3. Future Scope (Phase 2+)

## 3.1 Department-wise Popular Books

```text
popular:books:dept:{dept}
```

Examples:

```text
popular:books:dept:cse
popular:books:dept:ece
```

TTL: **1 hour**

Use Cases:

* Personalized recommendations
* Department reading trends

---

## 3.2 Global Popular Books

```text
popular:books:global
```

TTL: **1 hour**

Use Cases:

* Homepage recommendations
* Trending books section

---

## 3.3 Semester-wise Recommended Books

```text
sem:books:{dept}:{semester}
```

Examples:

```text
sem:books:cse:s5
sem:books:ece:s3
```

TTL: **30 days**

Use Cases:

* Semester-specific recommendations
* Curriculum support

---

## 3.4 Reading History

```text
user:{roll_no}:history
```

TTL: **30 days**

Use Cases:

* Reading analytics
* Personalized recommendations
* Borrow history

---

## 3.5 Reading List / Wishlist

```text
user:{roll_no}:reading_list
```

TTL: **7 days**

Use Cases:

* Wishlist management
* Quick access to saved books

---

## 3.6 Due-Date Reminder System

```text
notified:{roll_no}:{biblionumber}
```

TTL: **24 hours**

Use Cases:

* Push notifications
* Email reminders
* Fine prevention alerts

---

## 3.7 Recommendation Engine

### Potential Recommendation Models

#### Department-Based Recommendations

> Popular among CSE students

#### Semester-Based Recommendations

> Popular among Semester 5 students

#### Frequently Borrowed Together

Books commonly borrowed by the same students.

#### Faculty Recommended Books

Books recommended by course instructors.

#### Syllabus-Based Recommendations

Books linked directly to courses and semester curriculum.

---

# 4. Conclusion

Redis will significantly improve application performance by caching frequently accessed data and reducing repeated requests to the Koha backend.

The **Phase 1 implementation** focuses on performance optimization, scalability, and reduced backend load.

The **Phase 2 roadmap** leverages Redis data for personalized recommendations, reading analytics, academic assistance, trending content, and enhanced user engagement, providing a richer and more responsive digital library experience for NIT Calicut students and faculty.
