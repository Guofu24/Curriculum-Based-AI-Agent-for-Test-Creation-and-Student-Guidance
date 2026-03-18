import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ExamType(str, enum.Enum):
    MCQ = "mcq"
    ESSAY = "essay"
    MIXED = "mixed"


class DifficultyLevel(str, enum.Enum):
    BASIC = "basic"
    ADVANCED = "advanced"
    APPLICATION = "application"
    HIGH_APPLICATION = "high_application"
    CUSTOM = "custom"


class ExamStatus(str, enum.Enum):
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"
    REVIEWED = "reviewed"
    PUBLISHED = "published"


class QuestionType(str, enum.Enum):
    MCQ = "mcq"
    ESSAY = "essay"


class BloomLevel(str, enum.Enum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=True)
    textbook_id: Mapped[str] = mapped_column(ForeignKey("textbooks.id"), nullable=False)
    current_version_id: Mapped[str] = mapped_column(ForeignKey("exam_versions.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    exam_type: Mapped[ExamType] = mapped_column(SAEnum(ExamType, native_enum=False), nullable=False)
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        SAEnum(DifficultyLevel, native_enum=False),
        nullable=False,
    )
    status: Mapped[ExamStatus] = mapped_column(
        SAEnum(ExamStatus, native_enum=False),
        default=ExamStatus.GENERATING,
    )
    chapters: Mapped[list] = mapped_column(JSON, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    variant_number: Mapped[int] = mapped_column(Integer, default=1)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    instructions: Mapped[str] = mapped_column(Text, nullable=True, default="")
    output_language: Mapped[str] = mapped_column(String(20), nullable=False, default="vi")
    strict_scope_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    selected_scope_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    exam_spec_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    blueprint_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    review_notes_json: Mapped[list] = mapped_column(JSON, nullable=True)
    edit_history_json: Mapped[list] = mapped_column(JSON, nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, nullable=True)
    quality_scores_json: Mapped[list] = mapped_column(JSON, nullable=True)
    grounding_reports_json: Mapped[list] = mapped_column(JSON, nullable=True)
    duplicate_groups_json: Mapped[list] = mapped_column(JSON, nullable=True)
    provider_logs_json: Mapped[list] = mapped_column(JSON, nullable=True)
    edit_impact_level: Mapped[str] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    owner = relationship("User", back_populates="exams")
    course = relationship("Course", back_populates="exams")
    document = relationship("Textbook")
    exam_spec_record = relationship(
        "ExamSpecRecord",
        back_populates="exam",
        uselist=False,
        cascade="all, delete-orphan",
    )
    versions = relationship(
        "ExamVersion",
        back_populates="exam",
        cascade="all, delete-orphan",
        foreign_keys="ExamVersion.exam_id",
    )
    current_version = relationship(
        "ExamVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )


class ExamSpecRecord(Base):
    __tablename__ = "exam_specs"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id"), nullable=False, unique=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("textbooks.id"), nullable=True)
    creator_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    exam_type: Mapped[str] = mapped_column(String(50), nullable=False)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False, default="mcq_single_answer")
    time_limit_minutes: Mapped[int] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="vi")
    instructions: Mapped[str] = mapped_column(Text, nullable=True, default="")
    normalized_instructions: Mapped[str] = mapped_column(Text, nullable=True, default="")
    strict_scope_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bloom_distribution_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    question_mix_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    formatting_preferences_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    selected_scope_json: Mapped[list] = mapped_column(JSON, nullable=True)
    source_prompt: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=True, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    exam = relationship("Exam", back_populates="exam_spec_record")
    scopes = relationship(
        "ExamSpecScopeRecord",
        back_populates="exam_spec",
        cascade="all, delete-orphan",
    )
    blueprint_cells = relationship(
        "BlueprintCellRecord",
        back_populates="exam_spec",
        cascade="all, delete-orphan",
    )


class ExamSpecScopeRecord(Base):
    __tablename__ = "exam_spec_scopes"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    exam_spec_id: Mapped[str] = mapped_column(ForeignKey("exam_specs.id"), nullable=False)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), nullable=True)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(50), nullable=False, default="topic")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_from: Mapped[int] = mapped_column(Integer, nullable=True)
    page_to: Mapped[int] = mapped_column(Integer, nullable=True)
    tags_json: Mapped[list] = mapped_column(JSON, nullable=True)

    exam_spec = relationship("ExamSpecRecord", back_populates="scopes")


class BlueprintCellRecord(Base):
    __tablename__ = "blueprint_cells"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    exam_spec_id: Mapped[str] = mapped_column(ForeignKey("exam_specs.id"), nullable=False)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), nullable=True)
    cell_key: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_unit_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False)
    bloom_level: Mapped[str] = mapped_column(String(50), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overgenerate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    exam_spec = relationship("ExamSpecRecord", back_populates="blueprint_cells")


class ExamVersion(Base):
    __tablename__ = "exam_versions"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    parent_version_id: Mapped[str] = mapped_column(ForeignKey("exam_versions.id"), nullable=True)
    change_summary: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exam = relationship("Exam", back_populates="versions", foreign_keys=[exam_id])
    parent_version = relationship("ExamVersion", remote_side="ExamVersion.id")
    questions = relationship(
        "ExamQuestion",
        back_populates="exam_version",
        cascade="all, delete-orphan",
        foreign_keys="ExamQuestion.exam_version_id",
    )
    edit_operations = relationship(
        "EditOperation",
        back_populates="exam_version",
        cascade="all, delete-orphan",
    )


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id"), nullable=False)
    exam_version_id: Mapped[str] = mapped_column(ForeignKey("exam_versions.id"), nullable=True)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    blueprint_cell_key: Mapped[str] = mapped_column(String(128), nullable=True)
    question_type: Mapped[QuestionType] = mapped_column(
        SAEnum(QuestionType, native_enum=False),
        nullable=False,
    )
    bloom_level: Mapped[BloomLevel] = mapped_column(
        SAEnum(BloomLevel, native_enum=False),
        nullable=False,
    )
    difficulty_score: Mapped[float] = mapped_column(Float, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=True)
    source_chunks: Mapped[list] = mapped_column(JSON, nullable=True)
    source_evidence_json: Mapped[list] = mapped_column(JSON, nullable=True)
    scope_tags_json: Mapped[list] = mapped_column(JSON, nullable=True)
    warnings_json: Mapped[list] = mapped_column(JSON, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(50),
        nullable=True,
        default="pending",
    )
    is_human_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_notes: Mapped[str] = mapped_column(Text, nullable=True)
    quality_score_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    grounding_report_json: Mapped[dict] = mapped_column(JSON, nullable=True)

    exam_version = relationship("ExamVersion", back_populates="questions", foreign_keys=[exam_version_id])


class EditOperation(Base):
    __tablename__ = "edit_operations"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    exam_version_id: Mapped[str] = mapped_column(ForeignKey("exam_versions.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    edit_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_question_id: Mapped[str] = mapped_column(String(255), nullable=True)
    old_value: Mapped[dict] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict] = mapped_column(JSON, nullable=True)
    prompt_used: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exam_version = relationship("ExamVersion", back_populates="edit_operations")
