from datetime import datetime, timezone

from sqlalchemy import DateTime, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    roll_no: Mapped[str] = mapped_column(Text, primary_key=True)

    # Koha OPAC session cookie -- used for backend-to-Koha requests, never sent to the client.
    cgisessid: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AES-GCM encrypted {roll_no, password} bytes. NULL when remember-me is not enabled.
    creds_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # bcrypt hash of the current refresh token -- never the raw token.
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
