# Redis Session & Account Cache Design

## Overview

Koha remains the **single source of truth**.

Redis is used for:

* Session management
* Fast account page loading
* Loan information caching
* Fine information caching
* Instant book ownership checks for Book Detail pages

No Koha state is persisted in PostgreSQL.

---

# 1. Session Store

## Key

```text
session:{session_token}
```

Example:

```text
session:7f8c2b9d4ef3ab19
```

## Value

```json
{
  "cgisessid": "abc123xyz",

  "user": {
    "patron_id": 33419,
    "roll_no": "B210123CS",
    "name": "ADARSH P A",
    "branch_code": "LIB",
    "category_code": "UG"
  },

  "expires_at": "2026-06-15T10:00:00Z"
}
```

## TTL

```text
24 hours
```

>[!NOTE]
To be decided since we don’t know the actual Koha Login timeout. We can reduce this to an optimal time.

## Purpose

```text
Session Token
 ↓
Redis Session
 ↓
CGISESSID
 ↓
Koha
```

The frontend never receives the Koha `CGISESSID`.

Instead, it receives a backend-generated random alphanumeric string.

Multiple devices naturally create independent sessions.

---

# 2. Account Cache

## Key

```text
account:{roll_no}
```

Example:

```text
account:B210001CS
```

## Value

```json
{
  "loan_summary": {
    "loan_count": 3,
    "loan_limit": 8
  },

  // We need to calculate this based on parsed data
  "fine_summary": {
    "outstanding_fine": 150
  },

  "checked_out_books": [
    {
      "biblio_id": 1234,
      "title": "Operating Systems",
      "due_date": "2026-06-20",
      "renewals_left": 2
    },
    {
      "biblio_id": 5678,
      "title": "Computer Networks",
      "due_date": "2026-06-25",
      "renewals_left": 1
    }
  ],

  "fine_history": [
    {
      "amount": 50,
      "date": "2026-01-10",
      "status": "Paid"
    },
    {
      "amount": 100,
      "date": "2026-05-01",
      "status": "Unpaid"
    }
  ],

  "last_synced_at": "2026-06-14T10:00:00Z"
}
```

Actually this cache tag can be split into multiple smaller components since it’s not mandatory that all events happen through our app. It is possible that it happened through the library counter.

So we might need to set a shorter TTL or refresh this data in the background by parsing Koha API’s HTML response as and when required.

Of course, we can reduce the complexity by just telling the user to re-login in case they’ve interacted with the counter directly. Parsing long Koha HTML responses every time is useless.

## Purpose

Used to serve:

* Profile page
* Borrowed books page
* Fine summary
* Fine history

without contacting Koha on every request.

A single Koha scrape populates all account-related data.

---

# 3. Borrowed Books Set

## Key

```text
borrowed_books:{roll_no}
```

Example:

```text
borrowed_books:B210001CS
```

## Redis Set Members

```text
1234
5678
9012
```

Where each member is a `biblio_id`.

---

## Purpose

Used internally to enrich Book Detail responses.

### Check if current user has borrowed the book

```python
redis.sismember(
    f"borrowed_books:{roll_no}",
    biblio_id
)
```

### UI Logic

```text
If borrowed:
    Show Renew button

Else:
    Show Check Availability button
```

This avoids scanning the cached loan list whenever a Book Detail page is opened.

---

# API Usage

## GET /account

Returns:

```json
{
  "name": "ADARSH P A",
  "loan_count": 3,
  "loan_limit": 8,
  "outstanding_fine": 150
}
```

Source:

```text
account:{roll_no}
```

---

## GET /loans

Returns:

```json
{
  "items": [...]
}
```

Source:

```text
checked_out_books
```

---

## GET /fines/history

Returns:

```json
{
  "items": [...]
}
```

Source:

```text
fine_history
```

---

## GET /books/{biblio_id}

Returns normal book information enriched with user context.

Example:

```json
{
  "biblio_id": 1234,
  "title": "Operating Systems",

  "availability": {
    ...
  },

  "current_user": {
    "borrowed": true
  }
}
```

Internally:

```python
borrowed = redis.sismember(
    f"borrowed_books:{roll_no}",
    biblio_id
)
```

---

# Data Flow

## Login

```text
Flutter
 ↓
Backend
 ↓
Koha Login
 ↓
Receive CGISESSID
 ↓
Fetch Account Page
 ↓
Parse User Info
 ↓
Parse Loans
 ↓
Parse Fines
 ↓
Generate Session Token
 ↓
Store session in Redis
 ↓
Store account cache
 ↓
Build borrowed_books set
 ↓
Return Session Token
```

Example response:

```json
{
  "session_token": "7f8c2b9d4ef3ab19"
}
```

---

## Profile Page

```text
Flutter
 ↓
GET /account
 ↓
Session Token
 ↓
Redis Session
 ↓
Roll Number
 ↓
Account Cache
 ↓
Response
```

No Koha request required.

---

## Loans Page

I’ve only noticed a page for history of late dues in the mockup UI, and I’m not sure if we’ll be having this page. 

```text
Flutter
 ↓
GET /loans
 ↓
Session Token
 ↓
Redis Session
 ↓
Roll Number
 ↓
Account Cache
 ↓
Response
```

No Koha request required.

---

## Book Detail Page

```text
Flutter
 ↓
GET /books/{biblio_id}
 ↓
Session Token
 ↓
Redis Session
 ↓
Roll Number
 ↓
Borrowed Books Lookup
 ↓
Enrich Response
```

No Koha request required for ownership checks.

---

## Renewals

```text
Flutter
 ↓
POST /renew
 ↓
Session Token
 ↓
Redis Session
 ↓
CGISESSID
 ↓
Koha
 ↓
Refresh Account Cache
 ↓
Rebuild Borrowed Books Set
```

Renewals always contact Koha live.

>[!NOTE]
We will be only allowing for renewals and not for paying fines because the fine paying process is super long and we can’t automate that like UPI unless there is support from the campus (which is highly unlikely).

---

# Notes

* Do NOT store user passwords.
* Do NOT duplicate loans/fines in PostgreSQL.
* Koha remains the source of truth.
* Redis acts only as a session and performance cache.
* The frontend never receives Koha's `CGISESSID`.
* Availability checks and renewals should always contact Koha live.
* `borrowed_books` is derived from `checked_out_books` and should be rebuilt whenever the account cache is refreshed.
* If Koha invalidates a `CGISESSID`, the corresponding Redis session should be deleted and the user should be asked to log in again.

---

# Redis Footprint

Per active user:

```text
session:{session_token}
account:{roll_no}
borrowed_books:{roll_no}
```

Only three Redis key families are maintained.
