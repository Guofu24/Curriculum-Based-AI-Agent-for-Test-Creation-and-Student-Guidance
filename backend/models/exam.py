import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Text, ForeignKey, Enum as SAEnum, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

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
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    textbook_id: Mapped[str] = mapped_column(ForeignKey("textbooks.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    exam_type: Mapped[ExamType] = mapped_column(SAEnum(ExamType), nullable=False)
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        SAEnum(DifficultyLevel), nullable=False
    )
    status: Mapped[ExamStatus] = mapped_column(
        SAEnum(ExamStatus), default=ExamStatus.GENERATING
    )
    chapters: Mapped[dict] = mapped_column(JSON, nullable=False)  # list of chapter numbers
    config: Mapped[dict] = mapped_column(JSON, nullable=False)  # full generation config
    variant_number: Mapped[int] = mapped_column(Integer, default=1)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="exams")
    questions = relationship("ExamQuestion", back_populates="exam", cascade="all, delete-orphan")


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id"), nullable=False)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(
        SAEnum(QuestionType), nullable=False
    )
    bloom_level: Mapped[BloomLevel] = mapped_column(
        SAEnum(BloomLevel), nullable=False
    )
    difficulty_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 - 1.0
    content: Mapped[str] = mapped_column(Text, nullable=False)  # question text
    options: Mapped[dict] = mapped_column(JSON, nullable=True)  # MCQ options {A, B, C, D}
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=True)
    source_chunks: Mapped[dict] = mapped_column(JSON, nullable=True)  # citations
    is_validated: Mapped[bool] = mapped_column(default=False)
    validation_notes: Mapped[str] = mapped_column(Text, nullable=True)

    exam = relationship("Exam", back_populates="questions")
