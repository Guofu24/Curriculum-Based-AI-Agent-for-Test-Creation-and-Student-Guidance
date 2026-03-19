"""add phase 3 quality metadata to feedback events

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-18 22:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("feedback_events", sa.Column("workflow_stage", sa.String(length=50), nullable=True))
    op.add_column("feedback_events", sa.Column("event_source", sa.String(length=50), nullable=True))
    op.add_column("feedback_events", sa.Column("review_status", sa.String(length=50), nullable=True))
    op.add_column(
        "feedback_events",
        sa.Column("reviewed_by_human", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("feedback_events", "reviewed_by_human")
    op.drop_column("feedback_events", "review_status")
    op.drop_column("feedback_events", "event_source")
    op.drop_column("feedback_events", "workflow_stage")
