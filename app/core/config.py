from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Koha API Specific
    KOHA_BASE_URL: str = "https://opac.nitc.ac.in/api/v1/public"
    KOHA_OPAC_URL: str = "https://opac.nitc.ac.in"  # base URL for opac-user.pl (CGI auth)
    KOHA_USERNAME: str | None = None
    KOHA_PASSWORD: str | None = None

    # Auth / JWT
    JWT_SECRET_KEY: str  # required -- set in .env, never hardcode
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 7

    # AES-GCM key for encrypting stored credentials (remember me)
    # Must be a 32-byte hex string (64 hex chars). Generate with: openssl rand -hex 32
    CREDS_ENCRYPTION_KEY: str | None = None  # optional; required only if remember-me is enabled

    # Koha login retries -- transient network/5xx failures only, never on wrong credentials
    MAX_KOHA_LOGIN_RETRIES: int = 3
    KOHA_LOGIN_TIMEOUT_SECONDS: float = 10.0

    ITEMS_PER_PAGE: int = 500

    # Seed Data
    SEED_DATA: bool = True # Set to False to skip starting workers, useful for testing

    # Delays, Retries & Timeouts
    AVAILABILITY_WORKER_DELAY: int = 10
    METADATA_WORKER_DELAY: int = 2
    
    MAX_METADATA_RETRIES: int = 5
    MAX_AVAILABILITY_500_RETRIES: int = 5
    
    KOHA_AVAILABILITY_TIMEOUT_SECONDS: float = 3.0

    # Google Books
    # Comma-separated list of API keys for rotation/fallback.
    # Example: GOOGLE_BOOKS_API_KEYS=key1,key2,key3
    GOOGLE_BOOKS_API_KEYS: str = ""
    GOOGLE_BOOKS_WORKER_DELAY: int = 60
    GOOGLE_BOOKS_SCAN_BATCH_SIZE: int = 10

    # Logging
    LOG_LEVEL: str = "INFO"
    
    LOG_FORMAT: str = "%(asctime)s | %(levelname)s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    LOG_DATE_FORMAT: str = "%d-%m-%Y %H:%M:%S IST" # IST timezone for logs
    
    LOG_FILE_PATH: str = "logs/app.log" # Set to "" to disable file logging
    LOG_MAX_BYTES: int = 10 * 1024 * 1024 # 10 MB
    LOG_BACKUP_COUNT: int = 5

    # DB
    DATABASE_URL: str

    # Redis
    CACHE_ENABLED: bool = True  # Set to False to disable Redis caching entirely
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
