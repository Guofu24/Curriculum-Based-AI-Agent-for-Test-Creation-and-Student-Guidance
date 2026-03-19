import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
logger = logging.getLogger(__name__)

# Older local databases were sometimes created with create_all() and then skipped
# later migrations, leaving existing tables without newer columns. These ALTERs
# are idempotent and keep dev databases compatible with the current models.
#
# Note: the active runtime is document-first, but compatibility statements still
# target historical `textbooks` / `textbook_chunks` tables until a dedicated
# persistence rename is scheduled.
SCHEMA_COMPATIBILITY_STATEMENTS = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) NOT NULL DEFAULT 'lecturer'",
    "ALTER TABLE textbooks ADD COLUMN IF NOT EXISTS course_id VARCHAR NULL",
    "ALTER TABLE textbooks ADD COLUMN IF NOT EXISTS file_storage_url VARCHAR(1000) NULL",
    "ALTER TABLE textbooks ADD COLUMN IF NOT EXISTS file_hash VARCHAR(128) NULL",
    "ALTER TABLE textbooks ADD COLUMN IF NOT EXISTS language VARCHAR(20) NULL DEFAULT 'vi'",
    "ALTER TABLE textbooks ADD COLUMN IF NOT EXISTS total_pages_or_slides INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE textbooks ADD COLUMN IF NOT EXISTS parse_error_message TEXT NULL",
    "ALTER TABLE textbooks ADD COLUMN IF NOT EXISTS curriculum_tree_json JSON NULL",
    "ALTER TABLE textbook_chunks ADD COLUMN IF NOT EXISTS section_id VARCHAR NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS course_id VARCHAR NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS current_version_id VARCHAR NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS instructions TEXT NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS output_language VARCHAR(20) NOT NULL DEFAULT 'vi'",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS strict_scope_flag BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS selected_scope_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS exam_spec_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS blueprint_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS review_notes_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS edit_history_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS quality_scores_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS grounding_reports_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS duplicate_groups_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS provider_logs_json JSON NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS edit_impact_level VARCHAR(20) NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NULL",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS published_at TIMESTAMP NULL",
    "ALTER TABLE exam_specs ADD COLUMN IF NOT EXISTS document_id VARCHAR NULL",
    "ALTER TABLE exam_specs ADD COLUMN IF NOT EXISTS question_type VARCHAR(50) NOT NULL DEFAULT 'mcq_single_answer'",
    "ALTER TABLE exam_specs ADD COLUMN IF NOT EXISTS normalized_instructions TEXT NULL",
    "ALTER TABLE blueprint_cells ADD COLUMN IF NOT EXISTS section_id VARCHAR NULL",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS exam_version_id VARCHAR NULL",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS blueprint_cell_key VARCHAR(128) NULL",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS rubric_json JSON NULL",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS source_evidence_json JSON NULL",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS scope_tags_json JSON NULL",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS warnings_json JSON NULL",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS verification_status VARCHAR(50) NULL DEFAULT 'pending'",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS is_human_edited BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS is_locked BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS quality_score_json JSON NULL",
    "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS grounding_report_json JSON NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS workflow_stage VARCHAR(50) NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS event_stage VARCHAR(50) NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS event_source VARCHAR(50) NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS source_type VARCHAR(50) NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS source_ref VARCHAR(255) NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS review_status VARCHAR(50) NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS reviewed_by_human BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS error_categories_json JSON NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS before_snapshot_ref VARCHAR(255) NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS after_snapshot_ref VARCHAR(255) NULL",
    "ALTER TABLE feedback_events ADD COLUMN IF NOT EXISTS linked_eval_sample_id VARCHAR(255) NULL",
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    import models  # noqa: F401 - ensure all tables are registered before create_all

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in SCHEMA_COMPATIBILITY_STATEMENTS:
            await conn.execute(text(statement))
        logger.info("Schema compatibility checks completed.")
