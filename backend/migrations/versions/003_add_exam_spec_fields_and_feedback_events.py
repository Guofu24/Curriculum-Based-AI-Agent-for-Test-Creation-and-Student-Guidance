"""Add exam SPEC fields and feedback_events table

Revision ID: 003
Revises: 002
Create Date: 2026-04-27

Adds the 4 SPEC fields to exams (blueprint, checkpoint_state,
generation_metadata, quality_metrics) and creates the feedback_events table
for quality signals and human review signals from the AI pipeline.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── exams: add SPEC fields (idempotent) ────────────────────────────────────
    for col_name, col_type in [
        ("blueprint", "JSONB"),
        ("checkpoint_state", "JSONB"),
        ("generation_metadata", "JSONB"),
        ("quality_metrics", "JSONB"),
    ]:
        op.execute(
            f"ALTER TABLE exams ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
        )

    # ── feedback_events ───────────────────────────────────────────────────────
    # Use CREATE TABLE IF NOT EXISTS so this is safe to re-run.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback_events (
            id UUID NOT NULL PRIMARY KEY,
            exam_id UUID NOT NULL,
            exam_version_id UUID REFERENCES exam_history(id) ON DELETE SET NULL,
            user_id UUID NOT NULL,
            question_id VARCHAR(255),
            signal_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20),
            workflow_stage VARCHAR(50),
            event_source VARCHAR(50),
            source_type VARCHAR(50),
            source_ref VARCHAR(255),
            review_status VARCHAR(20),
            reviewed_by_human VARCHAR(5),
            error_categories JSONB,
            before_snapshot_ref VARCHAR(255),
            after_snapshot_ref VARCHAR(255),
            payload JSONB,
            description TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
        """
    )
    # Create indexes idempotently
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_events_exam_id ON feedback_events (exam_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_events_user_id ON feedback_events (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_events_signal_type ON feedback_events (signal_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_events_review_status ON feedback_events (review_status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_events_created_at ON feedback_events (created_at)")


def downgrade() -> None:
    op.drop_table("feedback_events")
    op.drop_column("exams", "quality_metrics")
    op.drop_column("exams", "generation_metadata")
    op.drop_column("exams", "checkpoint_state")
    op.drop_column("exams", "blueprint")
