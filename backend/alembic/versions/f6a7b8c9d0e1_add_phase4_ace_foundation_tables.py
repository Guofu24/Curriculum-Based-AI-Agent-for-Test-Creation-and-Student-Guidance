"""add phase 4 ACE foundation tables and feedback metadata

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-18 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("feedback_events", sa.Column("event_stage", sa.String(length=50), nullable=True))
    op.add_column("feedback_events", sa.Column("source_type", sa.String(length=50), nullable=True))
    op.add_column("feedback_events", sa.Column("source_ref", sa.String(length=255), nullable=True))
    op.add_column("feedback_events", sa.Column("error_categories_json", sa.JSON(), nullable=True))
    op.add_column("feedback_events", sa.Column("before_snapshot_ref", sa.String(length=255), nullable=True))
    op.add_column("feedback_events", sa.Column("after_snapshot_ref", sa.String(length=255), nullable=True))
    op.add_column("feedback_events", sa.Column("linked_eval_sample_id", sa.String(length=255), nullable=True))

    op.create_table(
        "playbook_bullets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("bullet_type", sa.String(length=50), nullable=False),
        sa.Column("subject", sa.String(length=50), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("question_type", sa.String(length=50), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_signals_json", sa.JSON(), nullable=True),
        sa.Column("helpful_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("harmful_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.Column("created_from", sa.String(length=100), nullable=True),
        sa.Column("review_status", sa.String(length=50), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "reflection_candidates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("subject", sa.String(length=50), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("question_type", sa.String(length=50), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("proposed_title", sa.String(length=255), nullable=False),
        sa.Column("proposed_bullet_type", sa.String(length=50), nullable=False),
        sa.Column("proposed_bullet_text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_event_ids_json", sa.JSON(), nullable=True),
        sa.Column("source_eval_sample_ids_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("merge_key", sa.String(length=255), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("promoted_bullet_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["promoted_bullet_id"], ["playbook_bullets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merge_key"),
    )


def downgrade() -> None:
    op.drop_table("reflection_candidates")
    op.drop_table("playbook_bullets")
    op.drop_column("feedback_events", "linked_eval_sample_id")
    op.drop_column("feedback_events", "after_snapshot_ref")
    op.drop_column("feedback_events", "before_snapshot_ref")
    op.drop_column("feedback_events", "error_categories_json")
    op.drop_column("feedback_events", "source_ref")
    op.drop_column("feedback_events", "source_type")
    op.drop_column("feedback_events", "event_stage")
