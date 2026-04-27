"""Add updated_at to users table

Revision ID: 002
Revises: 001
Create Date: 2026-04-27

The User model has an updated_at column but the initial migration
(001_initial.py) never added it to the users table, causing:
  column users.updated_at does not exist
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "add_file_size_to_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "updated_at")
