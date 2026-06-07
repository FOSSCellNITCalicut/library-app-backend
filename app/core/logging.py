from datetime import datetime
import os
from zoneinfo import ZoneInfo
import logging
from logging.handlers import RotatingFileHandler
import sys

from app.core.config import settings

# Formatter for IST
class ISTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(
            record.created,
            tz=ZoneInfo("Asia/Kolkata")
        )

        if datefmt:
            return dt.strftime(datefmt)

        return dt.isoformat()


def configure_logging(
    level: str = "INFO",
    log_file: str | None = settings.LOG_FILE_PATH,
    max_bytes: int = settings.LOG_MAX_BYTES,
    backup_count: int = settings.LOG_BACKUP_COUNT,
):
    root = logging.getLogger()
    root.setLevel(level)

    formatter = ISTFormatter(
        fmt=settings.LOG_FORMAT,
        datefmt=settings.LOG_DATE_FORMAT
    )

    root.handlers.clear() # Clear existing handlers

    # Log to stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    # Log to file with rotation
    if log_file:
        log_dir = os.path.dirname(log_file) or "."
        os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            filename=log_file, 
            maxBytes=max_bytes, 
            backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Set log level for noisy libraries to WARNING
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
