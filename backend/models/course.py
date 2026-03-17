import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class CourseRole(str, enum.Enum):
    LECTURER = "lecturer"
    TEACHING_ASSISTANT = "teaching_assistant"
    STUDENT = "student"


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    academic_level: Mapped[str] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    owner = relationship("User", back_populates="owned_courses")
    memberships = relationship(
        "CourseMembership",
        back_populates="course",
        cascade="all, delete-orphan",
    )
    documents = relationship("Textbook", back_populates="course")
    exams = relationship("Exam", back_populates="course")
    objectives = relationship("LearningObjective", back_populates="course")


class CourseMembership(Base):
    __tablename__ = "course_memberships"
    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_course_membership_course_user"),
    )

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[CourseRole] = mapped_column(
        SAEnum(CourseRole, native_enum=False),
        nullable=False,
        default=CourseRole.TEACHING_ASSISTANT,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="memberships")
    user = relationship("User", back_populates="course_memberships")
