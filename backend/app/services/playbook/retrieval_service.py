from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.models.playbook import PlaybookBullet, PlaybookBulletStatus, PlaybookBulletType
from app.services.playbook.store_service import PlaybookService


STAGE_TYPE_HINTS = {
    "generation": {
        PlaybookBulletType.HARD_RULE.value,
        PlaybookBulletType.GENERATION_HEURISTIC.value,
        PlaybookBulletType.SUBJECT_HINT.value,
    },
    "verification": {
        PlaybookBulletType.HARD_RULE.value,
        PlaybookBulletType.VERIFIER_HINT.value,
        PlaybookBulletType.FAILURE_PATTERN.value,
    },
    "review": {
        PlaybookBulletType.REVIEW_HEURISTIC.value,
        PlaybookBulletType.FAILURE_PATTERN.value,
        PlaybookBulletType.HARD_RULE.value,
    },
}


@dataclass
class PlaybookRetrievalOutcome:
    mode: str
    stage: str
    matched_bullets: list[PlaybookBullet]
    attached_bullets: list[PlaybookBullet]

    def as_prompt_lines(self) -> list[str]:
        return [
            f"[{bullet.bullet_type.value}] {bullet.content}"
            for bullet in self.attached_bullets
        ]

    def _serialize_bullet(self, bullet: PlaybookBullet) -> dict:
        return {
            "bullet_id": bullet.id,
            "title": bullet.title,
            "bullet_type": bullet.bullet_type.value,
            "confidence": bullet.confidence,
            "tags": list(bullet.tags_json or []),
        }

    def as_event_payload(self) -> dict:
        serialized_matched = [
            self._serialize_bullet(bullet)
            for bullet in self.matched_bullets
        ]
        serialized_attached = [
            self._serialize_bullet(bullet)
            for bullet in self.attached_bullets
        ]
        return {
            "retrieval_mode": self.mode,
            "stage": self.stage,
            "matched_count": len(self.matched_bullets),
            "attached_count": len(self.attached_bullets),
            "would_attach_count": len(self.matched_bullets),
            "matched_bullets": serialized_matched,
            "would_attach_bullets": serialized_matched,
            "attached_bullets": serialized_attached,
        }


class PlaybookRetrievalService:
    def __init__(self, db):
        self.db = db
        self.store = PlaybookService(db)

    def _score_bullet(
        self,
        bullet: PlaybookBullet,
        *,
        stage: str,
        subject: str,
        language: str,
        question_type: str,
        scope_units: list[dict] | None,
        error_categories: list[str] | None,
    ) -> float:
        if bullet.status != PlaybookBulletStatus.APPROVED:
            return 0.0
        if bullet.subject not in {"", subject}:
            return 0.0
        if bullet.language not in {"", language}:
            return 0.0
        if bullet.question_type not in {"", question_type}:
            return 0.0

        score = 0.2 + float(bullet.confidence or 0.0)
        scope_payload = dict(bullet.scope_json or {})
        stages = {
            str(item).strip().lower()
            for item in (scope_payload.get("stages") or [])
            if str(item).strip()
        }
        scope_types = {
            str(item).strip().lower()
            for item in (scope_payload.get("scope_types") or [])
            if str(item).strip()
        }
        category_tags = {
            str(item).strip().lower()
            for item in (scope_payload.get("error_categories") or [])
            if str(item).strip()
        }
        request_scope_types = {
            str(item.get("scope_type") or "").strip().lower()
            for item in (scope_units or [])
            if isinstance(item, dict)
        }
        request_error_categories = {
            str(item).strip().lower()
            for item in (error_categories or [])
            if str(item).strip()
        }

        if not stages or stage in stages:
            score += 1.5
        if stage in STAGE_TYPE_HINTS and bullet.bullet_type.value in STAGE_TYPE_HINTS[stage]:
            score += 1.0
        if scope_types and request_scope_types and scope_types & request_scope_types:
            score += 0.6
        if category_tags and request_error_categories and category_tags & request_error_categories:
            score += 1.2
        if request_error_categories and any(
            tag in request_error_categories for tag in (bullet.tags_json or [])
        ):
            score += 0.5
        return score

    async def retrieve(
        self,
        *,
        stage: str,
        subject: str = "physics",
        language: str = "vi",
        question_type: str = "mcq_single_answer",
        scope_units: list[dict] | None = None,
        error_categories: list[str] | None = None,
    ) -> PlaybookRetrievalOutcome:
        mode = settings.PLAYBOOK_RETRIEVAL_MODE
        if mode == "off":
            return PlaybookRetrievalOutcome(
                mode=mode,
                stage=stage,
                matched_bullets=[],
                attached_bullets=[],
            )

        bullets = await self.store.list_bullets(status="approved", limit=200)
        ranked = sorted(
            (
                (
                    self._score_bullet(
                        bullet,
                        stage=stage,
                        subject=subject,
                        language=language,
                        question_type=question_type,
                        scope_units=scope_units,
                        error_categories=error_categories,
                    ),
                    bullet,
                )
                for bullet in bullets
            ),
            key=lambda item: (-item[0], item[1].created_at),
        )
        matched_bullets = [
            bullet
            for score, bullet in ranked
            if score > 1.0
        ][: max(int(settings.PLAYBOOK_RETRIEVAL_LIMIT or 3), 1)]
        attached_bullets = matched_bullets if mode == "limited" else []
        return PlaybookRetrievalOutcome(
            mode=mode,
            stage=stage,
            matched_bullets=matched_bullets,
            attached_bullets=attached_bullets,
        )

