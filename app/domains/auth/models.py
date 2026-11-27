from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, LargeBinary, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(user_type = 'student' AND emp_id IS NULL) "
            "OR (user_type = 'faculty' AND emp_id = roll_no)",
            name="ck_users_institutional_identity",
        ),
    )

    roll_no: Mapped[str] = mapped_column(Text, primary_key=True)

    # Faculty use their employee ID as their Koha login ID. ``roll_no`` remains
    # the stable, globally unique Koha identity used by existing API routes.
    emp_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)

    # Koha OPAC session cookie -- used for backend-to-Koha requests, never sent to the client.
    cgisessid: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Google identity is permanently bound to one institutional account.
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True, index=True, nullable=True)
    is_google_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    user_type: Mapped[str] = mapped_column(
        Text, default="student", server_default="student", nullable=False
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
