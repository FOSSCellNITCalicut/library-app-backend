import logging

from app.core.config import settings
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

url = make_url(settings.DATABASE_URL)

logger.warning(
    "Database configured (host=%s, db=%s)",
    url.host,
    url.database,
)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as db:
        yield db
