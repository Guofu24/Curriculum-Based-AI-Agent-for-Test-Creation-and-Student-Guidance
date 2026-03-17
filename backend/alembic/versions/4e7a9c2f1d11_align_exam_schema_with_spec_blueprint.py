"""align exam schema with spec-first blueprint workflow

Revision ID: 4e7a9c2f1d11
Revises: fe39fdc8172a
Create Date: 2026-03-17 12:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4e7a9c2f1d11"
down_revision: Union[str, None] = "fe39fdc8172a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("exams", sa.Column("instructions", sa.Text(), nullable=True))
    op.add_column(
        "exams",
        sa.Column("output_language", sa.String(length=20), nullable=False, server_default="vi"),
    )
    op.add_column(
        "exams",
        sa.Column("strict_scope_flag", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("exams", sa.Column("selected_scope_json", sa.JSON(), nullable=True))
    op.add_column("exams", sa.Column("exam_spec_json", sa.JSON(), nullable=True))
    op.add_column("exams", sa.Column("blueprint_json", sa.JSON(), nullable=True))
    op.add_column("exams", sa.Column("review_notes_json", sa.JSON(), nullable=True))
    op.add_column("exams", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.add_column("exams", sa.Column("published_at", sa.DateTime(), nullable=True))

    op.add_column("exam_questions", sa.Column("blueprint_cell_key", sa.String(length=128), nullable=True))
    op.add_column("exam_questions", sa.Column("rubric_json", sa.JSON(), nullable=True))
    op.add_column("exam_questions", sa.Column("source_evidence_json", sa.JSON(), nullable=True))
    op.add_column("exam_questions", sa.Column("scope_tags_json", sa.JSON(), nullable=True))
    op.add_column("exam_questions", sa.Column("warnings_json", sa.JSON(), nullable=True))
    op.add_column(
        "exam_questions",
        sa.Column(
            "verification_status",
            sa.String(length=50),
            nullable=True,
            server_default="pending",
        ),
    )
    op.add_column(
        "exam_questions",
        sa.Column(
            "is_human_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("exam_questions", "is_human_edited")
    op.drop_column("exam_questions", "verification_status")
    op.drop_column("exam_questions", "warnings_json")
    op.drop_column("exam_questions", "scope_tags_json")
    op.drop_column("exam_questions", "source_evidence_json")
    op.drop_column("exam_questions", "rubric_json")
    op.drop_column("exam_questions", "blueprint_cell_key")

    op.drop_column("exams", "published_at")
    op.drop_column("exams", "updated_at")
    op.drop_column("exams", "review_notes_json")
    op.drop_column("exams", "blueprint_json")
    op.drop_column("exams", "exam_spec_json")
    op.drop_column("exams", "selected_scope_json")
    op.drop_column("exams", "strict_scope_flag")
    op.drop_column("exams", "output_language")
    op.drop_column("exams", "instructions")
