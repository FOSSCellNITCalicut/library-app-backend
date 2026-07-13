# Library App Backend

FastAPI backend for the NITC library mobile app. It pre-computes a read-optimized
projection of the Koha ILS into PostgreSQL via background sync workers, enriches
book metadata (covers/descriptions) from Google Books, and caches hot reads in
Redis. All background workers run inside the FastAPI process as asyncio tasks
started by the app's lifespan.

## Tech stack

- **Python 3.10+** / FastAPI + Uvicorn
- **PostgreSQL 16** (system of record for the app)
- **Redis 7** (optional read cache)
- **Koha ILS** (upstream source — only touched by background workers)
- **Google Books API** (cover/description enrichment)
- **Alembic** for migrations

## Prerequisites

### Option A — Docker (recommended)
- Docker + Docker Compose

### Option B — Local (host-based)
- Python 3.10+
- A running PostgreSQL (default `localhost:5432`, db `library_app`, user `postgres`)
- A running Redis (default `localhost:6379`) — or set `CACHE_ENABLED=False`

## 1. Configure environment

Copy the example file and edit the values:

```bash
cp .env.example .env
```

Required/important variables (all read from `.env` by `app/core/config.py`):

| Variable | Purpose | Notes |
|---|---|---|
| `DATABASE_URL` | Async Postgres DSN | Host = `localhost` locally, `library-db` in Docker |
| `JWT_SECRET_KEY` | Signs auth JWTs | **Required.** `openssl rand -hex 32` |
| `CREDS_ENCRYPTION_KEY` | AES-GCM key for "remember me" | Optional; `openssl rand -hex 32` (32 bytes / 64 hex chars) |
| `KOHA_BASE_URL` | Koha public API base | Defaults to NITC OPAC |
| `KOHA_OPAC_URL` | Koha OPAC base (CGI auth) | Defaults to NITC OPAC |
| `KOHA_USERNAME` / `KOHA_PASSWORD` | Koha sync credentials | Needed by the sync workers |
| `GOOGLE_BOOKS_API_KEYS` | Comma-separated Google Books keys | For cover/description enrichment |
| `CACHE_ENABLED` | Enable Redis caching | `True`/`False` |
| `REDIS_URL` | Redis DSN | `redis://localhost:6379/0` locally, `redis://library-redis:6379/0` in Docker |
| `SEED_DATA` | Start Koha sync workers | `True` to sync from Koha, `False` for pure API/testing |
| `HOST_PORT` | Docker host port for the API | Used by compose to avoid clashing with a local server |

## 2. Run with Docker (recommended)

```bash
cp .env.example .env        # then fill in JWT_SECRET_KEY etc.
docker compose up --build
```

This starts three services:

- `library-db` (Postgres 16) on `localhost:5432`
- `library-redis` (Redis 7) on `localhost:6379`
- `library-api` — runs `alembic upgrade head` (via `entrypoint.sh`), then
  `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`, published on
  `${HOST_PORT:-8000}` → `8000`.

In Docker, the API service overrides `DATABASE_URL` / `REDIS_URL` to use the
`library-db` / `library-redis` service names, so the container `.env` hostnames
don't matter for the DB/Redis.

On startup the app:
1. Runs Alembic migrations.
2. Initializes the Redis cache.
3. Starts background workers (availability + metadata if `SEED_DATA=True`,
   plus metadata-cleanup and Google Books workers always).
4. Serves HTTP on `http://localhost:8000` with `GET /health`.

### Run the Docker stack alongside a local uvicorn

Set a different host port so the container and your local server don't collide:

```bash
# In .env:
HOST_PORT=8001

docker compose up -d                       # API container on localhost:8001
source venv/bin/activate
uvicorn app.main:app --reload --port 8000  # local server on localhost:8000
```

Both share the same Postgres/Redis.

### Useful commands

```bash
docker compose logs -f library-api    # tail API/worker logs
docker compose down                   # stop (keep data volume)
docker compose down -v                # stop and reset the DB
```

## 3. Manual / host-based setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies (PostgreSQL + Redis clients included)
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
#    - set DATABASE_URL to localhost
#    - set REDIS_URL to localhost (or CACHE_ENABLED=False)

# 4. Apply migrations
alembic upgrade head

# 5. Run the API (lifespan starts the background workers)
uvicorn app.main:app --reload
```

The API serves on `http://localhost:8000` with `/health` available. Background
workers (availability/metadata) only start when `SEED_DATA=True` — set it in
`.env` if you want the catalog to populate from Koha.

> If you want Google Books cover enrichment to backfill/populate, let the worker
> run for a while. Running with `--reload` still works, but a single uninterrupted
> run (no `--reload`) avoids restarting the scan loop mid-batch.

## 4. Testing the API

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/books/browse
curl "http://localhost:8000/api/v1/books/search?q=python"
curl http://localhost:8000/api/v1/books/1
curl "http://localhost:8000/api/v1/books/search/isbn?isbn=9781234567890"
```

Interactive docs: **http://localhost:8000/docs**

> If the API runs on a non-default port (e.g. `HOST_PORT=8001`), replace `8000`
> with `8001` in the URLs above.

## 5. One-off scripts

`scripts/seed_missing_books.py` seeds books that exist in Koha and are available
but never appear in the `/items` browse endpoint (so the availability worker
never discovers them). It reads a newline-separated list of biblio IDs.

```bash
# Dry run (writes CSVs, does not touch the DB)
python -m scripts.seed_missing_books --ids-file scripts/missing_ids.txt

# Commit a small live test first
python -m scripts.seed_missing_books --ids-file scripts/missing_ids.txt --limit 5 --commit
```

## 6. Project layout

```
app/
  main.py                 # FastAPI entrypoint + lifespan (starts workers)
  core/                   # config, database, cache, logging
  api/v1/                 # versioned routers (books, auth, users, ...)
  domains/                # books, auth, users, sync, catalog, curriculum, ...
  integrations/           # koha/, google_books/ clients
  workers/                # enrichment (google books)
  db/                     # models, seeds, triggers
alembic/                  # migrations
scripts/                  # one-off operational scripts
documentation/            # architecture, api, auth, database, caching, ...
```

See the `documentation/` folder for full design details
(architecture, API, auth, database schema, Redis caching, retrieval/RAG).
