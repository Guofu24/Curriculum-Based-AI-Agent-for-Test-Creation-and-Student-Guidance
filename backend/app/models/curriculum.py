import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("textbooks.id"), nullable=False)
    parent_section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), nullable=True)
    section_title: Mapped[str] = mapped_column(String(500), nullable=False)
    section_type: Mapped[str] = mapped_column(String(50), nullable=False, default="topic")
    section_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_from: Mapped[int] = mapped_column(Integer, nullable=True)
    page_to: Mapped[int] = mapped_column(Integer, nullable=True)
    scope_label: Mapped[str] = mapped_column(String(255), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    document = relationship("Textbook", back_populates="sections")
    parent_section = relationship("Section", remote_side="Section.id", back_populates="child_sections")
    child_sections = relationship("Section", back_populates="parent_section")
    objectives = relationship("LearningObjective", back_populates="section")


class LearningObjective(Base):
    __tablename__ = "learning_objectives"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), nullable=True)
    objective_text: Mapped[str] = mapped_column(Text, nullable=False)
    objective_level: Mapped[str] = mapped_column(String(100), nullable=True)
    tags_json: Mapped[list] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    course = relationship("Course", back_populates="objectives")
    section = relationship("Section", back_populates="objectives")

