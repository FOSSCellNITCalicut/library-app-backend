# Library App Backend

FastAPI backend for a library management system. Pre-computes an efficient read model from Koha ILS via periodic sync, with PostgreSQL for storage and background workers for metadata/availability enrichment.

## Prerequisites

- Python 3.13+
- PostgreSQL (running on `localhost:5432`)

## Setup

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

Edit `.env`:

```
DATABASE_URL=postgresql://postgres:nitc@localhost:5432/library_app
```

## Database Setup

```bash
# Create the database- library_app

# Run migrations
alembic upgrade head

# (optional) Generate a new migration after model changes
alembic revision --autogenerate -m "description"
```


See `documentation` folder for full info
