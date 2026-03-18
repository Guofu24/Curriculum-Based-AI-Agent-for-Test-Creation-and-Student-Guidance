from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.mvp import normalize_physics_subject
from models.course import Course, CourseMembership, CourseRole


class CourseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_course(
        self,
        owner_user_id: str,
        course_name: str,
        subject: str,
        academic_level: str | None = None,
        description: str | None = None,
    ) -> Course:
        subject = normalize_physics_subject(subject)
        course = Course(
            owner_user_id=owner_user_id,
            course_name=course_name,
            subject=subject,
            academic_level=academic_level,
            description=description,
        )
        self.db.add(course)
        await self.db.flush()
        self.db.add(
            CourseMembership(
                course_id=course.id,
                user_id=owner_user_id,
                role=CourseRole.LECTURER,
            )
        )
        await self.db.flush()
        return await self.get_course(course.id, owner_user_id)

    async def get_course(self, course_id: str, user_id: str) -> Course | None:
        if not await self.has_course_access(course_id, user_id):
            return None
        result = await self.db.execute(
            select(Course)
            .where(Course.id == course_id)
            .options(selectinload(Course.memberships), selectinload(Course.documents))
        )
        return result.scalar_one_or_none()

    async def get_courses_for_user(self, user_id: str) -> list[Course]:
        membership_subquery = (
            select(CourseMembership.course_id)
            .where(CourseMembership.user_id == user_id)
        )
        result = await self.db.execute(
            select(Course)
            .where(
                or_(
                    Course.owner_user_id == user_id,
                    Course.id.in_(membership_subquery),
                )
            )
            .options(selectinload(Course.memberships), selectinload(Course.documents))
            .order_by(Course.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def has_course_access(self, course_id: str | None, user_id: str) -> bool:
        if not course_id:
            return True
        membership_exists = await self.db.execute(
            select(CourseMembership.id).where(
                CourseMembership.course_id == course_id,
                CourseMembership.user_id == user_id,
            )
        )
        owner_exists = await self.db.execute(
            select(Course.id).where(
                Course.id == course_id,
                Course.owner_user_id == user_id,
            )
        )
        return bool(membership_exists.scalar_one_or_none() or owner_exists.scalar_one_or_none())

    async def get_course_role(self, course_id: str, user_id: str) -> str | None:
        owner_exists = await self.db.execute(
            select(Course.id).where(
                Course.id == course_id,
                Course.owner_user_id == user_id,
            )
        )
        if owner_exists.scalar_one_or_none():
            return CourseRole.LECTURER.value

        membership = await self.db.execute(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.user_id == user_id,
            )
        )
        item = membership.scalar_one_or_none()
        return item.role.value if item else None
