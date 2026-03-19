from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.playbook import (
    PlaybookBullet,
    PlaybookBulletStatus,
    PlaybookBulletType,
)


SEED_PLAYBOOK_BULLETS = (
    {
        "status": PlaybookBulletStatus.APPROVED,
        "title": "Section scope is a hard boundary",
        "bullet_type": PlaybookBulletType.HARD_RULE,
        "subject": "physics",
        "language": "vi",
        "question_type": "mcq_single_answer",
        "scope_json": {
            "stages": ["generation", "verification"],
            "scope_types": ["chapter", "lesson", "topic"],
            "error_categories": ["scope_leak"],
        },
        "content": (
            "Chi su dung evidence nam trong cac `section_id` da duoc chon. "
            "Neu chunk ho tro nam ngoai scope hoac khong truy vet duoc section_id, "
            "khong duoc dung de tao hoac giu cau hoi."
        ),
        "rationale": "Scope leak la loi nghiem trong nhat cua active Physics MVP.",
        "source_signals_json": [
            {"kind": "phase3_metric", "name": "scope_violation_rate"},
            {"kind": "phase3_error", "category": "scope_leak"},
        ],
        "confidence": 0.96,
        "tags_json": ["scope", "grounding", "safety"],
        "created_from": "phase4_seed",
        "review_status": "approved_seed",
    },
    {
        "status": PlaybookBulletStatus.APPROVED,
        "title": "Physics MCQ distractors should stay in the same semantic frame",
        "bullet_type": PlaybookBulletType.GENERATION_HEURISTIC,
        "subject": "physics",
        "language": "vi",
        "question_type": "mcq_single_answer",
        "scope_json": {
            "stages": ["generation", "review"],
            "error_categories": ["ambiguous_options", "wrong_answer_key"],
        },
        "content": (
            "Voi MCQ Vat ly, 4 lua chon nen cung kieu dai luong, don vi, hoac vai tro khai niem. "
            "Tranh distractor lac he, nhieu dap an cung dung mot phan, hoac correct_answer khong khop label A/B/C/D."
        ),
        "rationale": "Giam wrong answer key va ambiguous options trong review.",
        "source_signals_json": [
            {"kind": "phase3_error", "category": "ambiguous_options"},
            {"kind": "phase3_error", "category": "wrong_answer_key"},
        ],
        "confidence": 0.88,
        "tags_json": ["mcq", "distractors", "answer_key"],
        "created_from": "phase4_seed",
        "review_status": "approved_seed",
    },
    {
        "status": PlaybookBulletStatus.APPROVED,
        "title": "Verifier should treat missing evidence references as weak evidence",
        "bullet_type": PlaybookBulletType.VERIFIER_HINT,
        "subject": "physics",
        "language": "vi",
        "question_type": "mcq_single_answer",
        "scope_json": {
            "stages": ["verification"],
            "error_categories": ["weak_evidence", "verifier_false_pass"],
        },
        "content": (
            "Neu explanation khong noi ro chi tiet tu evidence, hoac source_evidence trong/rong, "
            "coi do la weak evidence ngay ca khi cau hoi co ve hop ly."
        ),
        "rationale": "Giam verifier false pass va lam ro canh bao evidence.",
        "source_signals_json": [
            {"kind": "phase3_error", "category": "weak_evidence"},
            {"kind": "phase3_error", "category": "verifier_false_pass"},
        ],
        "confidence": 0.91,
        "tags_json": ["verifier", "evidence", "warnings"],
        "created_from": "phase4_seed",
        "review_status": "approved_seed",
    },
)


class PlaybookService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_seed_bullets(self) -> None:
        existing_count = await self.db.scalar(select(func.count()).select_from(PlaybookBullet))
        if int(existing_count or 0) > 0:
            return
        for payload in SEED_PLAYBOOK_BULLETS:
            self.db.add(PlaybookBullet(**payload))
        await self.db.flush()

    async def list_bullets(
        self,
        *,
        status: str | None = None,
        bullet_type: str | None = None,
        limit: int = 100,
        auto_seed: bool = True,
    ) -> list[PlaybookBullet]:
        if auto_seed:
            await self.ensure_seed_bullets()

        query = select(PlaybookBullet).order_by(
            PlaybookBullet.updated_at.desc(),
            PlaybookBullet.created_at.desc(),
        )
        if status:
            query = query.where(PlaybookBullet.status == PlaybookBulletStatus(status))
        if bullet_type:
            query = query.where(PlaybookBullet.bullet_type == PlaybookBulletType(bullet_type))
        result = await self.db.execute(query.limit(limit))
        return list(result.scalars().all())

    async def get_bullet(self, bullet_id: str) -> PlaybookBullet | None:
        await self.ensure_seed_bullets()
        result = await self.db.execute(
            select(PlaybookBullet).where(PlaybookBullet.id == bullet_id)
        )
        return result.scalar_one_or_none()

    async def create_bullet(
        self,
        *,
        title: str,
        bullet_type: str,
        content: str,
        subject: str = "physics",
        language: str = "vi",
        question_type: str = "mcq_single_answer",
        scope: dict | None = None,
        rationale: str | None = None,
        source_signals: list[dict] | None = None,
        confidence: float = 0.5,
        tags: list[str] | None = None,
        created_from: str | None = None,
        review_status: str | None = None,
        status: str = "draft",
    ) -> PlaybookBullet:
        bullet = PlaybookBullet(
            status=PlaybookBulletStatus(status),
            title=title,
            bullet_type=PlaybookBulletType(bullet_type),
            subject=subject,
            language=language,
            question_type=question_type,
            scope_json=scope or {},
            content=content,
            rationale=rationale,
            source_signals_json=list(source_signals or []),
            confidence=confidence,
            tags_json=list(tags or []),
            created_from=created_from,
            review_status=review_status,
        )
        self.db.add(bullet)
        await self.db.flush()
        return bullet

    async def archive_bullet(self, bullet_id: str) -> PlaybookBullet:
        bullet = await self.get_bullet(bullet_id)
        if not bullet:
            raise ValueError("Playbook bullet not found")
        bullet.status = PlaybookBulletStatus.ARCHIVED
        bullet.archived_at = datetime.utcnow()
        bullet.review_status = "archived"
        bullet.version = int(bullet.version or 1) + 1
        await self.db.flush()
        return bullet

    async def reject_bullet(self, bullet_id: str) -> PlaybookBullet:
        bullet = await self.get_bullet(bullet_id)
        if not bullet:
            raise ValueError("Playbook bullet not found")
        bullet.status = PlaybookBulletStatus.REJECTED
        bullet.review_status = "rejected"
        bullet.version = int(bullet.version or 1) + 1
        await self.db.flush()
        return bullet

    async def build_overview(self, *, user_id: str) -> dict:
        from services.feedback.store_service import FeedbackStoreService
        from services.playbook.reflection_service import ReflectionCandidateService
        from services.playbook.warmup_service import WarmupExportService

        bullets = await self.list_bullets(limit=200)
        candidates = await ReflectionCandidateService(self.db).list_candidates(limit=100)
        feedback_summary = await FeedbackStoreService(self.db).build_summary(user_id=user_id)
        warmup_export = await WarmupExportService(self.db).build_user_export(user_id=user_id)

        approved_bullets = [bullet for bullet in bullets if bullet.status == PlaybookBulletStatus.APPROVED]
        candidate_bullets = [bullet for bullet in bullets if bullet.status == PlaybookBulletStatus.CANDIDATE]
        archived_bullets = [bullet for bullet in bullets if bullet.status == PlaybookBulletStatus.ARCHIVED]
        promoted_candidates = [item for item in candidates if item.status.value == "promoted"]
        last_reflection_run_at = None
        if candidates:
            last_reflection_run_at = max(item.updated_at or item.created_at for item in candidates)

        return {
            "retrieval_mode": settings.PLAYBOOK_RETRIEVAL_MODE,
            "retrieval_limit": int(settings.PLAYBOOK_RETRIEVAL_LIMIT or 3),
            "feedback_event_count": feedback_summary["total_events"],
            "approved_bullet_count": len(approved_bullets),
            "candidate_bullet_count": len(candidate_bullets),
            "archived_bullet_count": len(archived_bullets),
            "reflection_candidate_count": len(candidates),
            "promoted_candidate_count": len(promoted_candidates),
            "warmup_exam_case_count": len(warmup_export["exam_cases"]),
            "warmup_question_case_count": len(warmup_export["question_cases"]),
            "warmup_feedback_case_count": len(warmup_export["feedback_cases"]),
            "top_feedback_categories": [
                {"name": item["category"], "count": item["count"]}
                for item in feedback_summary["top_error_categories"]
            ],
            "recent_bullets": approved_bullets[:5],
            "recent_candidates": candidates[:5],
            "last_reflection_run_at": last_reflection_run_at,
        }
