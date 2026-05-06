"""Add TextbookKnowledge model

Revision ID: f9b6cde5788e
Revises: 003
Create Date: 2026-05-06 03:09:49.714456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f9b6cde5788e'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create textbook_knowledge table (Bug 1 fix: was missing from auto-generated migration)
    op.create_table(
        'textbook_knowledge',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('namespace', sa.String(length=255), nullable=False),
        sa.Column('chapter', sa.String(length=255), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    )
    op.create_index('ix_textbook_knowledge_namespace', 'textbook_knowledge', ['namespace'], unique=False)

    op.create_index(op.f('ix_exams_status'), 'exams', ['status'], unique=False)
    op.alter_column('users', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))


def downgrade() -> None:
    op.alter_column('users', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.drop_index(op.f('ix_exams_status'), table_name='exams')
    op.drop_index('ix_textbook_knowledge_namespace', table_name='textbook_knowledge')
    op.drop_table('textbook_knowledge')
