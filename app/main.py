import asyncio
import logging
import subprocess
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app import __version__, configure_logging
from app.integrations.koha.client import KohaClient
from app.workers.availability_worker import AvailabilityWorker
from app.workers.metadata_worker import MetadataWorker


configure_logging()
logger = logging.getLogger(__name__)


def run_migrations() -> None:
    logger.info("Running Alembic Upgrade Head")
    
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        logger.error("alembic upgrade failed: %s", result.stderr)
        raise RuntimeError(f"alembic upgrade failed: {result.stderr}")
    
    logger.info("Alembic Upgrade Head Complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()

    availability_client = KohaClient()
    metadata_client = KohaClient()

    availability_worker = AvailabilityWorker(client=availability_client)
    metadata_worker = MetadataWorker(client=metadata_client)

    # Start both workers tasks concurrently. They will run until the application is shutting down.
    availability_task = asyncio.create_task(
        availability_worker.run(), name="availability-worker"
    )
    metadata_task = asyncio.create_task(
        metadata_worker.run(), name="metadata-worker"
    )

    logger.info("Workers started")

    try:
        yield
    finally:
        logger.info("Stopping workers")
        for task in (availability_task, metadata_task):
            task.cancel()

        # Wait for both tasks to finish, ignoring any exceptions raised due to cancellation
        await asyncio.gather(availability_task, metadata_task, return_exceptions=True)

        # Close the Koha clients, ignoring any exceptions that occur during closing
        for client in (availability_client, metadata_client):
            try:
                await client.aclose()
            except (RuntimeError, httpx.HTTPError) as e:
                logger.warning("Error closing Koha client: %s", e)

        logger.info("Workers stopped")


app = FastAPI(
    title="Library App Backend",
    version=__version__,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}
