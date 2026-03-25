from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.api.routers.auth import get_current_user
from app.schemas.course import CourseCreateRequest, CourseMembershipResponse, CourseResponse
from app.services.courses.service import CourseService
from app.utils.security import require_roles
from app.models.user import UserRole

router = APIRouter(prefix="/courses", tags=["courses"])


def _format_course(course) -> CourseResponse:
    memberships = [
        CourseMembershipResponse(
            user_id=membership.user_id,
            role=membership.role.value,
        )
        for membership in course.memberships
    ]
    return CourseResponse(
        id=course.id,
        owner_user_id=course.owner_user_id,
        course_name=course.course_name,
        subject=course.subject,
        academic_level=course.academic_level,
        description=course.description,
        created_at=course.created_at,
        updated_at=course.updated_at,
        membership_count=len(course.memberships or []),
        document_count=len(course.documents or []),
        memberships=memberships,
    )


@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    request: CourseCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
):
    service = CourseService(db)
    course = await service.create_course(
        owner_user_id=current_user.id,
        course_name=request.course_name,
        subject=request.subject,
        academic_level=request.academic_level,
        description=request.description,
    )
    return _format_course(course)


@router.get("/", response_model=list[CourseResponse])
async def list_courses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CourseService(db)
    courses = await service.get_courses_for_user(current_user.id)
    return [_format_course(course) for course in courses]


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CourseService(db)
    course = await service.get_course(course_id, current_user.id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return _format_course(course)

