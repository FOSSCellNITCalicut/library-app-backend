from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str

    KOHA_BASE_URL: str

    KOHA_USERNAME: str | None = None

    KOHA_PASSWORD: str | None = None

    ITEMS_PER_PAGE: int = 500

    AVAILABILITY_SYNC_DELAY: int = 10

    METADATA_WORKER_DELAY: int = 5

    class Config:
        env_file = ".env"

settings = Settings()
