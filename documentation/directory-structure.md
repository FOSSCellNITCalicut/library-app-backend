Note: the current directory needs some fixes and it will be done after first round tasks

backend/
│
├── app/
│   │
│   ├── main.py
│   │   # FastAPI entrypoint
│   │
│   ├── core/
│   │   │
│   │   ├── config.py
│   │   │   # Environment variables
│   │   │
│   │   ├── database.py
│   │   │   # SQLAlchemy engine/session
│   │   │
│   │   ├── redis.py
│   │   │   # Redis client
│   │   │
│   │   ├── security.py
│   │   │   # JWT helpers
│   │   │
│   │   ├── logging.py
│   │   │   # Central logging config
│   │   │
│   │   ├── exceptions.py
│   │   │   # Custom exceptions
│   │   │
│   │   └── constants.py
│   │       # Shared constants/TTL values
│   │
│   ├── api/
│   │   │
│   │   ├── dependencies.py
│   │   │   # FastAPI Depends()
│   │   │
│   │   ├── middleware/
│   │   │   │
│   │   │   ├── auth.py
│   │   │   │   # JWT auth middleware
│   │   │   │
│   │   │   ├── rate_limit.py
│   │   │   │   # Rate limiting
│   │   │   │
│   │   │   ├── request_id.py
│   │   │   │   # Correlation IDs
│   │   │   │
│   │   │   └── logging.py
│   │   │       # Request logging
│   │   │
│   │   └── v1/
│   │       │
│   │       ├── auth.py
│   │       │   # Login/logout routes
│   │       │
│   │       ├── books.py
│   │       │   # Browse + details endpoints
│   │       │
│   │       ├── search.py
│   │       │   # Search endpoint
│   │       │
│   │       ├── users.py
│   │       │   # Profile APIs
│   │       │
│   │       └── events.py
│   │           # User events APIs
│   │
│   ├── domains/
│   │   │
│   │   ├── books/
│   │   │   │
│   │   │   ├── models.py
│   │   │   │   # SQLAlchemy models
│   │   │   │
│   │   │   ├── schemas.py
│   │   │   │   # Pydantic request/response schemas
│   │   │   │
│   │   │   ├── repository.py
│   │   │   │   # DB queries only
│   │   │   │
│   │   │   ├── service.py
│   │   │   │   # Business logic
│   │   │   │
│   │   │   ├── search.py
│   │   │   │   # PostgreSQL FTS logic
│   │   │   │
│   │   │   ├── ranking.py
│   │   │   │   # Future ranking algorithms
│   │   │   │
│   │   │   └── cache.py
│   │   │       # Book cache logic
│   │   │
│   │   ├── auth/
│   │   │   │
│   │   │   ├── service.py
│   │   │   ├── oauth.py
│   │   │   ├── jwt.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── users/
│   │   │   │
│   │   │   ├── models.py
│   │   │   ├── repository.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── events/
│   │   │   │
│   │   │   ├── models.py
│   │   │   ├── repository.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   └── sync/
│   │       │
│   │       ├── models.py
│   │       │   # sync_state table
│   │       │
│   │       ├── repository.py
│   │       │
│   │       ├── service.py
│   │       │
│   │       └── enums.py
│   │           # sync statuses
│   │
│   ├── integrations/
│   │   │
│   │   ├── koha/
│   │   │   │
│   │   │   ├── client.py
│   │   │   │   # HTTP calls to Koha
│   │   │   │
│   │   │   ├── marc.py
│   │   │   │   # MARC parser
│   │   │   │
│   │   │   ├── normalizer.py
│   │   │   │   # Convert Koha -> internal schema
│   │   │   │
│   │   │   └── schemas.py
│   │   │
│   │   └── google_books/
│   │       │
│   │       ├── client.py
│   │       │   # Google Books requests
│   │       │
│   │       ├── normalizer.py
│   │       │
│   │       └── schemas.py
│   │
│   ├── workers/
│   │   │
│   │   ├── metadata_sync/
│   │   │   │
│   │   │   ├── worker.py
│   │   │   │   # Main metadata worker loop
│   │   │   │
│   │   │   ├── service.py
│   │   │   │   # Sync orchestration
│   │   │   │
│   │   │   └── scheduler.py
│   │   │       # Refresh scheduling
│   │   │
│   │   ├── availability_sync/
│   │   │   │
│   │   │   ├── worker.py
│   │   │   ├── service.py
│   │   │   └── scheduler.py
│   │   │
│   │   ├── enrichment/
│   │   │   │
│   │   │   ├── worker.py
│   │   │   │   # Google enrichment worker
│   │   │   │
│   │   │   └── service.py
│   │   │
│   │   └── cleanup/
│   │       │
│   │       ├── ghost_inventory.py
│   │       │
│   │       └── stale_metadata.py
│   │
│   ├── cache/
│   │   │
│   │   ├── keys.py
│   │   │   # Redis key generation
│   │   │
│   │   ├── books.py
│   │   │   # Book caching
│   │   │
│   │   ├── browse.py
│   │   │   # Browse feed cache
│   │   │
│   │   └── search.py
│   │       # Search cache
│   │
│   ├── shared/
│   │   │
│   │   ├── isbn.py
│   │   │   # ISBN cleanup
│   │   │
│   │   ├── pagination.py
│   │   │   # Shared pagination helpers
│   │   │
│   │   ├── dates.py
│   │   │   # Date utilities
│   │   │
│   │   ├── validators.py
│   │   │
│   │   └── schemas/
│   │       │
│   │       ├── pagination.py
│   │       │
│   │       └── common.py
│   │
│   ├── db/
│   │   │
│   │   ├── migrations/
│   │   │   # Alembic migrations
│   │   │
│   │   ├── triggers/
│   │   │   # SQL trigger definitions
│   │   │
│   │   └── seeds/
│   │       # Initial test data
│   │
│   └── tests/
│       │
│       ├── api/
│       ├── domains/
│       ├── workers/
│       └── integrations/
│
├── scripts/
│   │
│   ├── bootstrap_catalog.py
│   │   # Initial full sync
│   │
│   ├── reindex_search.py
│   │
│   └── backfill_metadata.py
│
├── docker/
│   │
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── docs/
│   │
│   ├── architecture.md
│   ├── api.md
│   ├── database.md
│   ├── caching.md
│   └── sync.md
│
├── .env.example
├── requirements.txt
└── README.md