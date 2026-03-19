"""
Generation Router

Handles MVP exam generation and scoped partial regeneration.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User, UserRole
from routers.exam_serializers import format_exam
from schemas.exam import ExamGenerationRequest, ExamPartialRegenerateRequest, ExamResponse, GenerationStep
from services.exam_service import ExamService
from utils.security import require_roles

router = APIRouter(prefix="/generate", tags=["generation"])


@router.post("/exam", response_model=ExamResponse)
async def generate_exam(
    request: ExamGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """
    Generate a new exam with the explicit MVP pipeline.

    Flow:
    1. Resolve scope -> 2. Build exam spec -> 3. Plan blueprint
    4. Retrieve evidence -> 5. Generate MCQ -> 6. Verify -> 7. Save version
    """
    service = ExamService(db)

    try:
        exam = await service.generate_exam(current_user.id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(exc)}")

    full_exam = await service.get_exam(exam.id, current_user.id)
    return format_exam(full_exam)


@router.post("/exam/stream")
async def generate_exam_stream(
    request: ExamGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """
    Generate exam with Server-Sent Events (SSE) progress updates.
    """

    async def event_stream():
        steps = [
            GenerationStep(step=1, name="Building exam spec", status="pending"),
            GenerationStep(step=2, name="Planning blueprint", status="pending"),
            GenerationStep(step=3, name="Retrieving evidence", status="pending"),
            GenerationStep(step=4, name="Generating and validating", status="pending"),
            GenerationStep(step=5, name="Finalizing exam", status="pending"),
        ]

        for step in steps:
            yield f"data: {step.model_dump_json()}\n\n"

        steps[0].status = "running"
        yield f"data: {steps[0].model_dump_json()}\n\n"
        await asyncio.sleep(0.5)
        steps[0].status = "completed"
        yield f"data: {steps[0].model_dump_json()}\n\n"

        steps[1].status = "running"
        yield f"data: {steps[1].model_dump_json()}\n\n"
        await asyncio.sleep(0.2)
        steps[1].status = "completed"
        yield f"data: {steps[1].model_dump_json()}\n\n"

        steps[2].status = "running"
        yield f"data: {steps[2].model_dump_json()}\n\n"
        await asyncio.sleep(0.2)
        steps[2].status = "completed"
        yield f"data: {steps[2].model_dump_json()}\n\n"

        steps[3].status = "running"
        yield f"data: {steps[3].model_dump_json()}\n\n"

        try:
            service = ExamService(db)
            exam = await service.generate_exam(current_user.id, request)
            await db.commit()
            committed_exam = await service.get_exam(exam.id, current_user.id)
            if committed_exam is None:
                raise RuntimeError("Generated exam could not be reloaded after commit")

            steps[3].status = "completed"
            yield f"data: {steps[3].model_dump_json()}\n\n"

            steps[4].status = "completed"
            steps[4].message = committed_exam.id
            yield f"data: {steps[4].model_dump_json()}\n\n"

            yield f"data: {json.dumps({'type': 'complete', 'exam_id': committed_exam.id})}\n\n"
        except Exception as exc:
            error_step = next((step for step in steps if step.status == "running"), steps[-1])
            error_step.status = "failed"
            error_step.message = str(exc)
            yield f"data: {error_step.model_dump_json()}\n\n"
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/partial-regenerate", response_model=ExamResponse)
async def partial_regenerate(
    request: ExamPartialRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """
    Regenerate specific questions in an existing exam version.
    """
    service = ExamService(db)

    try:
        exam = await service.partial_regenerate(current_user.id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    full_exam = await service.get_exam(exam.id, current_user.id)
    return format_exam(full_exam)
