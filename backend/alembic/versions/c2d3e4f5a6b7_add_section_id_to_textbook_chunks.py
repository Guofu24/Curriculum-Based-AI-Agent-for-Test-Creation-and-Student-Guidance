"""add section_id to textbook_chunks for deterministic scope filtering

Revision ID: c2d3e4f5a6b7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-18 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("textbook_chunks", sa.Column("section_id", sa.String(length=255), nullable=True))
    op.create_index("ix_textbook_chunks_section_id", "textbook_chunks", ["section_id"], unique=False)

    op.execute(
        """
        UPDATE textbook_chunks
        SET section_id = metadata_json::json ->> 'section_id'
        WHERE section_id IS NULL
          AND metadata_json IS NOT NULL
          AND metadata_json <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_textbook_chunks_section_id", table_name="textbook_chunks")
    op.drop_column("textbook_chunks", "section_id")
