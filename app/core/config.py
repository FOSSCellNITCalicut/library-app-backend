from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Koha API Specific
    KOHA_BASE_URL: str = "https://opac.nitc.ac.in/api/v1/public"
    KOHA_USERNAME: str | None = None
    KOHA_PASSWORD: str | None = None
    
    ITEMS_PER_PAGE: int = 500

    # Seed Data
    SEED_DATA: bool = True # Set to False to skip starting workers, useful for testing

    # Delays, Retries & Timeouts
    AVAILABILITY_WORKER_DELAY: int = 10
    METADATA_WORKER_DELAY: int = 2
    
    MAX_METADATA_RETRIES: int = 5
    MAX_AVAILABILITY_500_RETRIES: int = 5
    
    KOHA_AVAILABILITY_TIMEOUT_SECONDS: float = 3.0

    # Logging
    LOG_LEVEL: str = "INFO"
    
    LOG_FORMAT: str = "%(asctime)s | %(levelname)s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    LOG_DATE_FORMAT: str = "%d-%m-%Y %H:%M:%S IST" # IST timezone for logs
    
    LOG_FILE_PATH: str = "logs/app.log" # Set to "" to disable file logging
    LOG_MAX_BYTES: int = 10 * 1024 * 1024 # 10 MB
    LOG_BACKUP_COUNT: int = 5

    # DB
    DATABASE_URL: str

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
