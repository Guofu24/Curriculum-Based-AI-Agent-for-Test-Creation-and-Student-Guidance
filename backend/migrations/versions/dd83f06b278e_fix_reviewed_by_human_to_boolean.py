"""fix_reviewed_by_human_to_boolean

Revision ID: dd83f06b278e
Revises: f9b6cde5788e
Create Date: 2026-05-06 16:45:52.357418

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'dd83f06b278e'
down_revision: Union[str, None] = 'f9b6cde5788e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # VARCHAR(5) -> Boolean: requires explicit USING clause in PostgreSQL
    op.execute(
        "ALTER TABLE feedback_events "
        "ALTER COLUMN reviewed_by_human TYPE BOOLEAN "
        "USING (reviewed_by_human::text = 'true')"
    )
    op.alter_column(
        'textbook_knowledge', 'created_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        existing_server_default=sa.text('now()'),
    )


def downgrade() -> None:
    op.alter_column(
        'textbook_knowledge', 'created_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
        existing_server_default=sa.text('now()'),
    )
    op.execute(
        "ALTER TABLE feedback_events "
        "ALTER COLUMN reviewed_by_human TYPE VARCHAR(5) "
        "USING (CASE WHEN reviewed_by_human THEN 'true' ELSE 'false' END)"
    )
