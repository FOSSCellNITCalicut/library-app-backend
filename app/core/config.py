from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str

    KOHA_BASE_URL: str = "https://opac.nitc.ac.in/api/v1/public"

    KOHA_USERNAME: str | None = None

    KOHA_PASSWORD: str | None = None

    ITEMS_PER_PAGE: int = 500

    AVAILABILITY_SYNC_DELAY: int = 10

    METADATA_WORKER_DELAY: int = 5

    MAX_METADATA_RETRIES: int = 5

    MAX_AVAILABILITY_500_RETRIES: int = 5

    KOHA_AVAILABILITY_TIMEOUT_SECONDS: float = 3.0

    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
