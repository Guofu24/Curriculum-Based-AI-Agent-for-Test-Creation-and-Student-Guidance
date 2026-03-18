"""add feedback events table for structured review/regeneration signals

Revision ID: d4e5f6a7b8c9
Revises: 9c3d4e5f6a7b, c2d3e4f5a6b7
Create Date: 2026-03-18 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = ("9c3d4e5f6a7b", "c2d3e4f5a6b7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("exam_id", sa.String(), nullable=False),
        sa.Column("exam_version_id", sa.String(), nullable=True),
        sa.Column("question_id", sa.String(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("signal_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"]),
        sa.ForeignKeyConstraint(["exam_version_id"], ["exam_versions.id"]),
        sa.ForeignKeyConstraint(["question_id"], ["exam_questions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_events_exam_id", "feedback_events", ["exam_id"], unique=False)
    op.create_index(
        "ix_feedback_events_exam_version_id",
        "feedback_events",
        ["exam_version_id"],
        unique=False,
    )
    op.create_index("ix_feedback_events_question_id", "feedback_events", ["question_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_feedback_events_question_id", table_name="feedback_events")
    op.drop_index("ix_feedback_events_exam_version_id", table_name="feedback_events")
    op.drop_index("ix_feedback_events_exam_id", table_name="feedback_events")
    op.drop_table("feedback_events")
