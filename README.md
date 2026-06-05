# Library App Backend

FastAPI backend for a library management system. Pre-computes an efficient read model from Koha ILS via periodic sync, with PostgreSQL for storage and background workers for metadata/availability enrichment. The background workers run inside the FastAPI process as background asyncio tasks, started by the app's lifespan.

## Prerequisites

- Python 3.13+
- PostgreSQL (running on `localhost:5432`)

## Running with Docker Compose (recommended)

```bash
cp .env.example .env
docker compose up --build
```

This starts:

- `postgres` on `localhost:5432`
- `api` on `localhost:8000`

On startup the `api` process:

1. Runs `alembic upgrade head`.
2. Starts the availability and metadata workers as background asyncio tasks.
3. Exposes `GET /health`.

Tail logs:

```bash
docker compose logs -f api
```

Stop everything:

```bash
docker compose down
```

The compose stack uses the service name `postgres` as the database host inside `.env`, so the same file works for both compose and host-based Alembic runs against a local Postgres.

## Manual setup (host-based)

```bash
# 1. Clone the repo
git clone <repo-url> library-app-backend
cd library-app-backend

# 2. Create virtual environment and activate
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
```

Edit `.env` so `DATABASE_URL` points at a local Postgres on `localhost`:

```
DATABASE_URL=postgresql+asyncpg://postgres:nitc@localhost:5432/library_app
```

## Running the app

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

The lifespan hook will start the workers as background tasks. The API serves on `http://localhost:8000` with `/health` available.

## Running a single worker in isolation (for debugging)

Each worker module is also a standalone entrypoint:

```bash
python -m app.workers.availability_worker
python -m app.workers.metadata_worker
```

Running either of these directly bypasses FastAPI. Use this only for one-off debugging — running multiple workers in different processes is not currently supported.

See `documentation` folder for full info.
