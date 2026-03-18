"""add mvp scope records and exam spec fields

Revision ID: 9c3d4e5f6a7b
Revises: 7b8d5f4e2c21
Create Date: 2026-03-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c3d4e5f6a7b"
down_revision: Union[str, None] = "7b8d5f4e2c21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("exam_specs", sa.Column("document_id", sa.String(), nullable=True))
    op.add_column(
        "exam_specs",
        sa.Column("question_type", sa.String(length=50), nullable=False, server_default="mcq_single_answer"),
    )
    op.add_column("exam_specs", sa.Column("normalized_instructions", sa.Text(), nullable=True))
    op.add_column("blueprint_cells", sa.Column("section_id", sa.String(), nullable=True))

    op.create_table(
        "exam_spec_scopes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("exam_spec_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=True),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("scope_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["exam_spec_id"], ["exam_specs.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("exam_spec_scopes")
    op.drop_column("blueprint_cells", "section_id")
    op.drop_column("exam_specs", "normalized_instructions")
    op.drop_column("exam_specs", "question_type")
    op.drop_column("exam_specs", "document_id")
