# Library App Backend

FastAPI backend for a library management system. Pre-computes an efficient read model from Koha ILS via periodic sync, with PostgreSQL for storage and background workers for metadata/availability enrichment. The background workers run inside the FastAPI process as background asyncio tasks, started by the app's lifespan.

## Prerequisites

- Python 3.10+ (Dockerfile uses `python:3.10-slim`)
- PostgreSQL (running on `localhost:5432`)

## Running with Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

This starts:

- `db` (Postgres 16) on `localhost:5432`
- `api` on `localhost:8000`

The `api` service bind-mounts the project source to `/app` and runs uvicorn with `--reload`, so code edits on the host are picked up by the worker loop and the HTTP server without rebuilding the image.

On startup the `api` process:

1. Runs `alembic upgrade head` (async engine, against the live DB).
2. Starts the availability and metadata workers as background asyncio tasks.
3. Exposes `GET /health`.

### Running Docker alongside local uvicorn

To run the Docker stack and a local `uvicorn` dev server side-by-side, set a different host port for the API container:

```bash
# In .env, set:
HOST_PORT=8001

# Then start the stack:
docker compose up -d          # api container on localhost:8001

# In a separate terminal, run locally:
source venv/bin/activate
uvicorn app.main:app --reload --port 8000   # local on localhost:8000
```

This avoids port conflicts — both servers share the same PostgreSQL and can be tested independently.

### Useful docker commands

```bash
docker compose logs -f api     # tail api logs
docker compose down            # stop (keep data volume)
docker compose down -v         # stop and reset DB
```

The compose stack uses the service name `db` as the database host inside `.env`. 

## Manual setup (host-based)

```bash
# 1. Create virtual environment and activate
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
```

## Running the app

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

The lifespan hook will start the workers as background tasks. The API serves on `http://localhost:8000` with `/health` available.

## Testing the API

```bash
# Health check
curl http://localhost:8000/health

# Browse books
curl http://localhost:8000/api/v1/books/browse

# Search books
curl "http://localhost:8000/api/v1/books/search?q=python"

# Get book by biblio ID
curl http://localhost:8000/api/v1/books/1

# Search by ISBN
curl "http://localhost:8000/api/v1/books/search/isbn?isbn=9781234567890"
```
#### Or use the swagger ui: "http://localhost:8000/docs"

> If running Docker on a non-default port (e.g. `HOST_PORT=8001`), replace `8000` with `8001` in the URLs above.

See `documentation` folder for full info.
