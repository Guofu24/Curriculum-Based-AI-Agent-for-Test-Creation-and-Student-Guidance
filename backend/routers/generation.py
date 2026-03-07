"""
Generation Router

Handles exam generation and partial regeneration with SSE progress streaming.
"""
import json
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from routers.auth import get_current_user
from schemas.exam import (
    ExamGenerationRequest,
    ExamPartialRegenerateRequest,
    ExamResponse,
    GenerationStep,
    QuestionResponse,
    MCQOption,
)
from services.exam_service import ExamService

router = APIRouter(prefix="/generate", tags=["generation"])


@router.post("/exam", response_model=ExamResponse)
async def generate_exam(
    request: ExamGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a new exam using the multi-agent pipeline.

    This runs the full LangGraph workflow:
    1. Parse textbook → 2. Create blueprint → 3. Retrieve context →
    4. Generate questions → 5. Validate → 6. Finalize
    """
    service = ExamService(db)

    try:
        exam = await service.generate_exam(current_user.id, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    # Re-fetch with questions
    full_exam = await service.get_exam(exam.id, current_user.id)

    questions = sorted(full_exam.questions, key=lambda q: q.question_number)
    return ExamResponse(
        id=full_exam.id,
        title=full_exam.title,
        textbook_id=full_exam.textbook_id,
        exam_type=full_exam.exam_type.value,
        difficulty=full_exam.difficulty.value,
        status=full_exam.status.value,
        chapters=full_exam.chapters,
        variant_number=full_exam.variant_number,
        total_questions=full_exam.total_questions,
        quality_score=full_exam.quality_score,
        created_at=full_exam.created_at,
        questions=[_format_question(q) for q in questions],
    )


@router.post("/exam/stream")
async def generate_exam_stream(
    request: ExamGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate exam with Server-Sent Events (SSE) progress updates.

    The frontend's GenerationStepper component can subscribe to this
    to show real-time progress.
    """
    async def event_stream():
        steps = [
            GenerationStep(step=1, name="Parsing textbook", status="pending"),
            GenerationStep(step=2, name="Retrieving knowledge", status="pending"),
            GenerationStep(step=3, name="Generating questions", status="pending"),
            GenerationStep(step=4, name="Validating constraints", status="pending"),
            GenerationStep(step=5, name="Finalizing exam", status="pending"),
        ]

        # Emit initial state
        for s in steps:
            yield f"data: {s.model_dump_json()}\n\n"

        # Step 1: Parsing
        steps[0].status = "running"
        yield f"data: {steps[0].model_dump_json()}\n\n"
        await asyncio.sleep(0.5)  # allow frontend to render
        steps[0].status = "completed"
        yield f"data: {steps[0].model_dump_json()}\n\n"

        # Step 2: Retrieving
        steps[1].status = "running"
        yield f"data: {steps[1].model_dump_json()}\n\n"

        # Step 3: Generating (starts the actual generation)
        steps[2].status = "running"
        yield f"data: {steps[2].model_dump_json()}\n\n"

        try:
            service = ExamService(db)
            exam = await service.generate_exam(current_user.id, request)

            steps[1].status = "completed"
            yield f"data: {steps[1].model_dump_json()}\n\n"
            steps[2].status = "completed"
            yield f"data: {steps[2].model_dump_json()}\n\n"

            # Step 4: Validating
            steps[3].status = "completed"
            yield f"data: {steps[3].model_dump_json()}\n\n"

            # Step 5: Finalizing
            steps[4].status = "completed"
            steps[4].message = exam.id  # send exam ID
            yield f"data: {steps[4].model_dump_json()}\n\n"

            # Final: send complete signal
            yield f"data: {json.dumps({'type': 'complete', 'exam_id': exam.id})}\n\n"

        except Exception as e:
            error_step = next((s for s in steps if s.status == "running"), steps[-1])
            error_step.status = "failed"
            error_step.message = str(e)
            yield f"data: {error_step.model_dump_json()}\n\n"
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

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
    current_user: User = Depends(get_current_user),
):
    """
    Regenerate specific questions in an existing exam.

    Supports:
    - Regenerating specific questions by ID
    - Regenerating a range of questions (from X to Y)
    - Custom edit prompts per question
    """
    service = ExamService(db)

    try:
        exam = await service.partial_regenerate(current_user.id, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    full_exam = await service.get_exam(exam.id, current_user.id)
    questions = sorted(full_exam.questions, key=lambda q: q.question_number)

    return ExamResponse(
        id=full_exam.id,
        title=full_exam.title,
        textbook_id=full_exam.textbook_id,
        exam_type=full_exam.exam_type.value,
        difficulty=full_exam.difficulty.value,
        status=full_exam.status.value,
        chapters=full_exam.chapters,
        variant_number=full_exam.variant_number,
        total_questions=full_exam.total_questions,
        quality_score=full_exam.quality_score,
        created_at=full_exam.created_at,
        questions=[_format_question(q) for q in questions],
    )


def _format_question(q) -> QuestionResponse:
    options = None
    if q.options and isinstance(q.options, list):
        options = [MCQOption(label=o["label"], text=o["text"]) for o in q.options]

    return QuestionResponse(
        id=q.id,
        question_number=q.question_number,
        question_type=q.question_type.value,
        bloom_level=q.bloom_level.value,
        difficulty_score=q.difficulty_score,
        content=q.content,
        options=options,
        correct_answer=q.correct_answer,
        explanation=q.explanation,
        source_citations=q.source_chunks,
        is_validated=q.is_validated,
    )
