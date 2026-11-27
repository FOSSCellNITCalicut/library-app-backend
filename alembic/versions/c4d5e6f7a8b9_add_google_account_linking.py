"""add Google identity and account type fields to users

Revision ID: c4d5e6f7a8b9
Revises: 865bf0604c97
Create Date: 2026-11-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "865bf0604c97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("emp_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("google_sub", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "is_google_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("user_type", sa.Text(), server_default="student", nullable=False),
    )
    op.add_column("users", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_users_emp_id", "users", ["emp_id"])
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.create_check_constraint(
        "ck_users_institutional_identity",
        "users",
        "(user_type = 'student' AND emp_id IS NULL) "
        "OR (user_type = 'faculty' AND emp_id = roll_no)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_institutional_identity", "users", type_="check")
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_constraint("uq_users_emp_id", "users", type_="unique")
    op.drop_column("users", "last_verified_at")
    op.drop_column("users", "user_type")
    op.drop_column("users", "is_google_verified")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "emp_id")
