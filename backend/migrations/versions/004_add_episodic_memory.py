"""Add episodic memory columns to teacher_preferences

Revision ID: 004
Revises: 003
Create Date: 2026-05-07

Adds topic_history and reject_patterns JSONB columns to teacher_preferences
for cross-exam topic deduplication and teacher style learning.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "dd83f06b278e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE teacher_preferences ADD COLUMN IF NOT EXISTS topic_history JSONB"
    )
    op.execute(
        "ALTER TABLE teacher_preferences ADD COLUMN IF NOT EXISTS reject_patterns JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE teacher_preferences DROP COLUMN IF EXISTS topic_history")
    op.execute("ALTER TABLE teacher_preferences DROP COLUMN IF EXISTS reject_patterns")
