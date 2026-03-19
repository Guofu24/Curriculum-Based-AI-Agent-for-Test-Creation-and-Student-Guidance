from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User, UserRole
from routers.auth import get_current_user
from schemas.playbook import (
    PlaybookBulletResponse,
    PlaybookOverviewResponse,
    ReflectionCandidateResponse,
)
from services.playbook.reflection_service import ReflectionCandidateService
from services.playbook.store_service import PlaybookService
from services.playbook.warmup_service import WarmupExportService
from utils.security import require_roles

router = APIRouter(prefix="/playbook", tags=["playbook"])


def _serialize_bullet(bullet) -> dict:
    return PlaybookBulletResponse(
        id=bullet.id,
        status=bullet.status.value,
        title=bullet.title,
        bullet_type=bullet.bullet_type.value,
        scope=bullet.scope_json,
        subject=bullet.subject,
        language=bullet.language,
        question_type=bullet.question_type,
        content=bullet.content,
        rationale=bullet.rationale,
        source_signals=list(bullet.source_signals_json or []),
        helpful_count=int(bullet.helpful_count or 0),
        harmful_count=int(bullet.harmful_count or 0),
        confidence=float(bullet.confidence or 0.0),
        tags=list(bullet.tags_json or []),
        created_from=bullet.created_from,
        review_status=bullet.review_status,
        version=int(bullet.version or 1),
        archived_at=bullet.archived_at,
        created_at=bullet.created_at,
        updated_at=bullet.updated_at,
    ).model_dump()


def _serialize_candidate(candidate) -> dict:
    return ReflectionCandidateResponse(
        id=candidate.id,
        status=candidate.status.value,
        category=candidate.category,
        subject=candidate.subject,
        language=candidate.language,
        question_type=candidate.question_type,
        scope=candidate.scope_json,
        evidence=candidate.evidence_json,
        proposed_title=candidate.proposed_title,
        proposed_bullet_type=candidate.proposed_bullet_type.value,
        proposed_bullet_text=candidate.proposed_bullet_text,
        rationale=candidate.rationale,
        source_event_ids=list(candidate.source_event_ids_json or []),
        source_eval_sample_ids=list(candidate.source_eval_sample_ids_json or []),
        confidence=float(candidate.confidence or 0.0),
        merge_key=candidate.merge_key,
        review_notes=candidate.review_notes,
        promoted_bullet_id=candidate.promoted_bullet_id,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
        reviewed_at=candidate.reviewed_at,
    ).model_dump()


@router.get("/overview", response_model=PlaybookOverviewResponse)
async def get_playbook_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = await PlaybookService(db).build_overview(user_id=current_user.id)
    payload["recent_bullets"] = [_serialize_bullet(item) for item in payload["recent_bullets"]]
    payload["recent_candidates"] = [_serialize_candidate(item) for item in payload["recent_candidates"]]
    return payload


@router.get("/bullets", response_model=list[PlaybookBulletResponse])
async def list_playbook_bullets(
    status: str | None = Query(default=None),
    bullet_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    bullets = await PlaybookService(db).list_bullets(
        status=status,
        bullet_type=bullet_type,
        limit=limit,
    )
    return [_serialize_bullet(item) for item in bullets]


@router.post("/bullets/{bullet_id}/archive", response_model=PlaybookBulletResponse)
async def archive_playbook_bullet(
    bullet_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    _ = current_user
    try:
        bullet = await PlaybookService(db).archive_bullet(bullet_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _serialize_bullet(bullet)


@router.get("/candidates", response_model=list[ReflectionCandidateResponse])
async def list_reflection_candidates(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    candidates = await ReflectionCandidateService(db).list_candidates(status=status, limit=limit)
    return [_serialize_candidate(item) for item in candidates]


@router.post("/candidates/generate", response_model=list[ReflectionCandidateResponse])
async def generate_reflection_candidates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    candidates = await ReflectionCandidateService(db).generate_candidates(user_id=current_user.id)
    return [_serialize_candidate(item) for item in candidates]


@router.post("/candidates/{candidate_id}/promote", response_model=PlaybookBulletResponse)
async def promote_reflection_candidate(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    _ = current_user
    try:
        bullet = await ReflectionCandidateService(db).promote_candidate(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _serialize_bullet(bullet)


@router.post("/candidates/{candidate_id}/reject", response_model=ReflectionCandidateResponse)
async def reject_reflection_candidate(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    _ = current_user
    try:
        candidate = await ReflectionCandidateService(db).reject_candidate(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _serialize_candidate(candidate)


@router.get("/warmup-preview")
async def get_warmup_preview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await WarmupExportService(db).build_user_export(user_id=current_user.id)
