from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evals.phase3_eval import build_error_analysis, build_phase3_report
from models.playbook import (
    PlaybookBulletType,
    ReflectionCandidate,
    ReflectionCandidateStatus,
)
from services.feedback.store_service import FeedbackStoreService
from services.playbook.store_service import PlaybookService


REFLECTION_TEMPLATES = {
    "scope_leak": {
        "title": "Treat scope mismatch as a hard stop",
        "bullet_type": PlaybookBulletType.HARD_RULE,
        "text": (
            "Neu evidence hoac section_id cua chunk khong nam trong scope da chon, "
            "phai loai bo cau hoi thay vi co gang sua bang kien thuc ben ngoai."
        ),
        "stages": ["generation", "verification", "review"],
    },
    "weak_evidence": {
        "title": "Require explanation to point back to evidence",
        "bullet_type": PlaybookBulletType.VERIFIER_HINT,
        "text": (
            "Khi explanation khong tro lai duoc chunk/evidence cu the, danh dau `weak_evidence` "
            "va uu tien regenerate hon la publish."
        ),
        "stages": ["verification", "review"],
    },
    "wrong_answer_key": {
        "title": "Keep answer labels consistent with MCQ options",
        "bullet_type": PlaybookBulletType.GENERATION_HEURISTIC,
        "text": (
            "Moi cau MCQ phai co dung 4 lua chon A/B/C/D va `correct_answer` phai trung mot label "
            "co that trong danh sach options."
        ),
        "stages": ["generation", "review"],
    },
    "ambiguous_options": {
        "title": "Review distractor ambiguity before publish",
        "bullet_type": PlaybookBulletType.REVIEW_HEURISTIC,
        "text": (
            "Neu distractor co muc do ho tro tu evidence cao ngang dap an dung, "
            "ghi nhan `ambiguous_options` va yeu cau sua hoac regenerate."
        ),
        "stages": ["review", "verification"],
    },
    "duplicate_question": {
        "title": "Escalate duplicate items as a repeat generation failure",
        "bullet_type": PlaybookBulletType.FAILURE_PATTERN,
        "text": (
            "Khi nhieu cau hoi trung y/chung stem trong cung version, "
            "xem do la duplicate generation pattern va uu tien thay bang item moi."
        ),
        "stages": ["generation", "review"],
    },
    "retrieval_miss": {
        "title": "Low retrieval hit quality should block risky generation",
        "bullet_type": PlaybookBulletType.FAILURE_PATTERN,
        "text": (
            "Neu retrieval khong cham vao expected section coverage, "
            "giam muc do tin cay cua generation va ghi log de dieu tra retrieval miss."
        ),
        "stages": ["retrieval", "generation"],
    },
    "verifier_false_pass": {
        "title": "Verifier should stay conservative on weak evidence",
        "bullet_type": PlaybookBulletType.VERIFIER_HINT,
        "text": (
            "Neu question co evidence mong, warning mo ho, hoac explanation khong tro lai chunk cu the, "
            "uu tien warning/fail thay vi false pass."
        ),
        "stages": ["verification"],
    },
}


class ReflectionCandidateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_candidates(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ReflectionCandidate]:
        query = select(ReflectionCandidate).order_by(
            ReflectionCandidate.updated_at.desc(),
            ReflectionCandidate.created_at.desc(),
        )
        if status:
            query = query.where(ReflectionCandidate.status == ReflectionCandidateStatus(status))
        result = await self.db.execute(query.limit(limit))
        return list(result.scalars().all())

    async def generate_candidates(self, *, user_id: str) -> list[ReflectionCandidate]:
        feedback_events = await FeedbackStoreService(self.db).list_events(user_id=user_id, limit=2000)
        feedback_counter: Counter[str] = Counter()
        feedback_event_ids_by_category: dict[str, list[str]] = {}
        for event in feedback_events:
            categories = list(
                getattr(event, "error_categories_json", None)
                or (event.payload_json or {}).get("error_categories")
                or []
            )
            for category in categories:
                name = str(category).strip().lower()
                if not name:
                    continue
                feedback_counter.update([name])
                feedback_event_ids_by_category.setdefault(name, []).append(str(event.id))

        phase3_report = build_phase3_report(split="all")
        error_report = build_error_analysis(report=phase3_report)
        eval_counter = Counter(
            {
                str(item["category"]).strip().lower(): int(item["count"])
                for item in error_report["categories"]
            }
        )

        active_categories = sorted(
            set(feedback_counter) | set(eval_counter),
            key=lambda item: (-(feedback_counter[item] + eval_counter[item]), item),
        )

        created_or_updated: list[ReflectionCandidate] = []
        for category in active_categories:
            template = REFLECTION_TEMPLATES.get(category)
            if not template:
                continue
            eval_samples = [
                str(sample.get("sample_id") or "").strip()
                for sample in next(
                    (
                        item for item in error_report["categories"]
                        if str(item["category"]).strip().lower() == category
                    ),
                    {"samples": []},
                )["samples"]
                if str(sample.get("sample_id") or "").strip()
            ]
            merge_key = f"{category}:physics:vi:mcq_single_answer"
            result = await self.db.execute(
                select(ReflectionCandidate).where(ReflectionCandidate.merge_key == merge_key)
            )
            candidate = result.scalar_one_or_none()
            total_support = int(feedback_counter[category]) + int(eval_counter[category])
            confidence = min(0.97, 0.45 + 0.08 * total_support)
            evidence = {
                "feedback_count": int(feedback_counter[category]),
                "eval_count": int(eval_counter[category]),
                "sample_refs": eval_samples[:5],
                "top_signal_examples": feedback_event_ids_by_category.get(category, [])[:5],
            }

            if candidate is None:
                candidate = ReflectionCandidate(
                    status=ReflectionCandidateStatus.CANDIDATE,
                    category=category,
                    subject="physics",
                    language="vi",
                    question_type="mcq_single_answer",
                    scope_json={
                        "stages": list(template["stages"]),
                        "error_categories": [category],
                    },
                    evidence_json=evidence,
                    proposed_title=template["title"],
                    proposed_bullet_type=template["bullet_type"],
                    proposed_bullet_text=template["text"],
                    rationale=(
                        f"Derived from Phase 3 eval + runtime feedback. "
                        f"support={total_support}"
                    ),
                    source_event_ids_json=feedback_event_ids_by_category.get(category, [])[:10],
                    source_eval_sample_ids_json=eval_samples[:10],
                    confidence=confidence,
                    merge_key=merge_key,
                )
                self.db.add(candidate)
            elif candidate.status == ReflectionCandidateStatus.CANDIDATE:
                candidate.evidence_json = evidence
                candidate.source_event_ids_json = feedback_event_ids_by_category.get(category, [])[:10]
                candidate.source_eval_sample_ids_json = eval_samples[:10]
                candidate.confidence = confidence
                candidate.rationale = (
                    f"Derived from Phase 3 eval + runtime feedback. "
                    f"support={total_support}"
                )
            created_or_updated.append(candidate)

        await self.db.flush()
        return sorted(
            created_or_updated,
            key=lambda item: (-(item.confidence or 0.0), item.created_at),
        )

    async def promote_candidate(self, candidate_id: str):
        result = await self.db.execute(
            select(ReflectionCandidate).where(ReflectionCandidate.id == candidate_id)
        )
        candidate = result.scalar_one_or_none()
        if not candidate:
            raise ValueError("Reflection candidate not found")
        if candidate.promoted_bullet_id:
            return await PlaybookService(self.db).get_bullet(candidate.promoted_bullet_id)

        bullet = await PlaybookService(self.db).create_bullet(
            title=candidate.proposed_title,
            bullet_type=candidate.proposed_bullet_type.value,
            content=candidate.proposed_bullet_text,
            subject=candidate.subject,
            language=candidate.language,
            question_type=candidate.question_type,
            scope=dict(candidate.scope_json or {}),
            rationale=candidate.rationale,
            source_signals=[
                {
                    "kind": "reflection_candidate",
                    "candidate_id": candidate.id,
                    "category": candidate.category,
                }
            ],
            confidence=float(candidate.confidence or 0.5),
            tags=[candidate.category, "phase4_promoted"],
            created_from="reflection_candidate",
            review_status="approved",
            status="approved",
        )
        candidate.status = ReflectionCandidateStatus.PROMOTED
        candidate.promoted_bullet_id = bullet.id
        candidate.reviewed_at = datetime.utcnow()
        await self.db.flush()
        return bullet

    async def reject_candidate(self, candidate_id: str) -> ReflectionCandidate:
        result = await self.db.execute(
            select(ReflectionCandidate).where(ReflectionCandidate.id == candidate_id)
        )
        candidate = result.scalar_one_or_none()
        if not candidate:
            raise ValueError("Reflection candidate not found")
        candidate.status = ReflectionCandidateStatus.REJECTED
        candidate.reviewed_at = datetime.utcnow()
        await self.db.flush()
        return candidate
