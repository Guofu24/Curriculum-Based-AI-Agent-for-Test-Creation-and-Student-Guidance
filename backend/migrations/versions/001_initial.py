"""Initial migration - create all tables

Revision ID: 001
Revises:
Create Date: 2026-03-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('role', sa.String(50), nullable=True),
        sa.Column('department', sa.String(255), nullable=True),
        sa.Column('university', sa.String(255), nullable=True),
        sa.Column('is_email_verified', sa.Boolean(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=True),
        sa.Column('last_failed_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('totp_secret', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # Courses table
    op.create_table(
        'courses',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('course_name', sa.String(500), nullable=False),
        sa.Column('subject', sa.String(100), nullable=False),
        sa.Column('academic_level', sa.String(50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_courses_owner_user_id', 'courses', ['owner_user_id'])

    # Documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('course_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('file_name', sa.String(500), nullable=False),
        sa.Column('file_type', sa.String(10), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('file_hash', sa.String(64), nullable=True),
        sa.Column('file_storage_url', sa.String(1000), nullable=True),
        sa.Column('language', sa.String(10), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('parse_error_message', sa.String(2000), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.Column('total_pages_or_slides', sa.Integer(), nullable=True),
        sa.Column('total_chunks', sa.Integer(), nullable=True),
        sa.Column('curriculum_tree', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_documents_user_id', 'documents', ['user_id'])
    op.create_index('ix_documents_course_id', 'documents', ['course_id'])

    # Exams table
    op.create_table(
        'exams',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('course_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('exam_type', sa.String(50), nullable=True),
        sa.Column('difficulty', sa.String(50), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('chapters', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('selected_scope', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('output_language', sa.String(10), nullable=True),
        sa.Column('strict_scope_flag', sa.Boolean(), nullable=True),
        sa.Column('time_limit_minutes', sa.Integer(), nullable=True),
        sa.Column('variant_number', sa.Integer(), nullable=True),
        sa.Column('questions', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('total_questions', sa.Integer(), nullable=True),
        sa.Column('exam_spec', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('blueprint', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('quality_score', sa.Numeric(5, 4), nullable=True),
        sa.Column('quality_scores', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('grounding_reports', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('duplicate_groups', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('provider_logs', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('total_cost_usd', sa.Numeric(10, 4), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('current_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('version_count', sa.Integer(), nullable=True),
        sa.Column('verifier_pass_rate', sa.Numeric(5, 4), nullable=True),
        sa.Column('evidence_coverage_rate', sa.Numeric(5, 4), nullable=True),
        sa.Column('regenerate_count', sa.Integer(), nullable=True),
        sa.Column('human_edit_count', sa.Integer(), nullable=True),
        sa.Column('warning_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_exams_user_id', 'exams', ['user_id'])

    # Exam versions table
    op.create_table(
        'exam_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('exam_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('parent_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('change_summary', sa.Text(), nullable=True),
        sa.Column('questions', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('edit_operations', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_exam_versions_exam_id', 'exam_versions', ['exam_id'])

    # Feedback events table
    op.create_table(
        'feedback_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('exam_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('exam_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('signal_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), nullable=True),
        sa.Column('workflow_stage', sa.String(50), nullable=True),
        sa.Column('event_source', sa.String(50), nullable=True),
        sa.Column('source_type', sa.String(50), nullable=True),
        sa.Column('source_ref', sa.String(200), nullable=True),
        sa.Column('question_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('review_status', sa.String(50), nullable=True),
        sa.Column('reviewed_by_human', sa.Boolean(), nullable=True),
        sa.Column('error_categories', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('before_snapshot_ref', sa.String(200), nullable=True),
        sa.Column('after_snapshot_ref', sa.String(200), nullable=True),
        sa.Column('payload', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['exam_version_id'], ['exam_versions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_feedback_events_exam_id', 'feedback_events', ['exam_id'])

    # Refresh tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token_hash', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])

    # Teacher preferences table
    op.create_table(
        'teacher_preferences',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('preferred_bloom_distribution', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('preferred_exam_types', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('subject_focus', sa.String(100), nullable=True),
        sa.Column('style_notes', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
    )


def downgrade() -> None:
    op.drop_table('teacher_preferences')
    op.drop_table('refresh_tokens')
    op.drop_index('ix_feedback_events_exam_id', table_name='feedback_events')
    op.drop_table('feedback_events')
    op.drop_index('ix_exam_versions_exam_id', table_name='exam_versions')
    op.drop_table('exam_versions')
    op.drop_index('ix_exams_user_id', table_name='exams')
    op.drop_table('exams')
    op.drop_index('ix_documents_course_id', table_name='documents')
    op.drop_index('ix_documents_user_id', table_name='documents')
    op.drop_table('documents')
    op.drop_index('ix_courses_owner_user_id', table_name='courses')
    op.drop_table('courses')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
