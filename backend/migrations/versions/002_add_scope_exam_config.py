"""Add scope and exam_config columns to exams table

Revision ID: 002
Revises: 001
Create Date: 2026-03-28

This migration adds:
- exam_config column: stores the raw generation config as JSON
- scope column: stores the raw scope strings for generation
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add exam_config column to exams
    op.add_column(
        'exams',
        sa.Column('exam_config', postgresql.JSON(astext_type=sa.Text()), nullable=True)
    )
    # Add scope column to exams
    op.add_column(
        'exams',
        sa.Column('scope', postgresql.JSON(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('exams', 'scope')
    op.drop_column('exams', 'exam_config')
