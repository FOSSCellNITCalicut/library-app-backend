# Library App Backend

FastAPI backend for a library management system. Pre-computes an efficient read model from Koha ILS via periodic sync, with PostgreSQL for storage and background workers for metadata/availability enrichment. The background workers run inside the FastAPI process as background asyncio tasks, started by the app's lifespan.

## Prerequisites

- Python 3.10+ (Dockerfile uses `python:3.10-slim`)
- PostgreSQL (running on `localhost:5432`)

## Running with Docker Compose (recommended)

```bash
cp .env.example .env
docker compose up --build
```

This starts:

- `db` (Postgres 16) on `localhost:5432`
- `api` on `localhost:8000`

The `api` service bind-mounts the project source to `/app` and runs uvicorn with `--reload`, so code edits on the host are picked up by the worker loop and the HTTP server without rebuilding the image. 

Anonymous volumes overlay `/app/app/__pycache__` and `/app/alembic/__pycache__` so the container's bytecode cache doesn't sync back into the host tree.

On startup the `api` process:

1. Runs `alembic upgrade head` (async engine, against the live DB).
2. Starts the availability and metadata workers as background asyncio tasks.
3. Exposes `GET /health`.

Tail logs:

```bash
docker compose logs -f api
```

Stop everything (keep the data volume):

```bash
docker compose down
```

Reset the DB (drop the data volume too):

```bash
docker compose down -v
```

The compose stack uses the service name `db` as the database host inside `.env`.

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

## Running the app

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

The lifespan hook will start the workers as background tasks. The API serves on `http://localhost:8000` with `/health` available.

See `documentation` folder for full info.
