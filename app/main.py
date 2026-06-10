import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.core.logging import configure_logging 
from app.core.config import settings
from app.integrations.koha.client import KohaClient
from app.domains.sync.workers.availability_worker import AvailabilityWorker
from app.domains.sync.workers.metadata_cleanup_worker import MetadataCleanupWorker
from app.domains.sync.workers.metadata_worker import MetadataWorker

__version__ = "0.1.0"

configure_logging()
logger = logging.getLogger(__name__)

clients: list = []
tasks: list = []


@asynccontextmanager
async def lifespan(app: FastAPI):

    if settings.SEED_DATA:
        availability_client = KohaClient()
        metadata_client = KohaClient()

        clients.extend([availability_client, metadata_client]) # Keep references to clients to shutdown properly later

        availability_worker = AvailabilityWorker(client=availability_client)
        metadata_worker = MetadataWorker(client=metadata_client)

        # Start both workers tasks concurrently. They will run until the application is shutdown.
        availability_task = asyncio.create_task(
            availability_worker.run(), name="availability-worker"
        )
        
        logger.info("Availability Worker Started")
        
        metadata_task = asyncio.create_task(
            metadata_worker.run(), name="metadata-worker"
        )

        logger.info("Metadata Worker Started")

        tasks.extend([availability_task, metadata_task]) # Keep references to tasks to cancel properly later
    else:
        logger.info("SEED_DATA is False, skipping worker startup")

    # Start the metadata cleanup worker (runs regardless of SEED_DATA since it doesn't depend on Koha API)
    cleanup_worker = MetadataCleanupWorker()
    cleanup_task = asyncio.create_task(
        cleanup_worker.run(), name="metadata-cleanup-worker"
    )
    
    tasks.append(cleanup_task) # Keep reference to cleanup task to cancel properly later
    logger.info("Metadata Cleanup Worker Started")

    try:
        yield
    finally:
        logger.info("Stopping Workers...")

        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

        for client in clients:
            try:
                await client.aclose()
            except (RuntimeError, httpx.HTTPError) as e:
                logger.warning("Error closing Koha client: %s", e)

        logger.info("Workers Stopped")


app = FastAPI(
    title="Library App Backend",
    version=__version__,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}
