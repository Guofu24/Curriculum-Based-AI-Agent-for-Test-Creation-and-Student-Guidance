"""add quality, grounding, dedup, provider_logs columns

Revision ID: a1b2c3d4e5f6
Revises: 3579bf44957f
Create Date: 2026-03-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '3579bf44957f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Exam-level columns (Phase 1-5 aggregate data)
    op.add_column('exams', sa.Column('quality_scores_json', sa.JSON(), nullable=True))
    op.add_column('exams', sa.Column('grounding_reports_json', sa.JSON(), nullable=True))
    op.add_column('exams', sa.Column('duplicate_groups_json', sa.JSON(), nullable=True))
    op.add_column('exams', sa.Column('provider_logs_json', sa.JSON(), nullable=True))
    op.add_column('exams', sa.Column('edit_impact_level', sa.String(length=20), nullable=True))

    # Per-question columns (individual quality + grounding)
    op.add_column('exam_questions', sa.Column('quality_score_json', sa.JSON(), nullable=True))
    op.add_column('exam_questions', sa.Column('grounding_report_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('exam_questions', 'grounding_report_json')
    op.drop_column('exam_questions', 'quality_score_json')
    op.drop_column('exams', 'edit_impact_level')
    op.drop_column('exams', 'provider_logs_json')
    op.drop_column('exams', 'duplicate_groups_json')
    op.drop_column('exams', 'grounding_reports_json')
    op.drop_column('exams', 'quality_scores_json')
