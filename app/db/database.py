from app.core.config import settings

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(
    DATABASE_URL, 
    pool_size=20,
    max_overflow=10,
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

def get_db():
    with AsyncSessionLocal() as db:
        yield db
