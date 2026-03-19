from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlaybookBulletResponse(BaseModel):
    id: str
    status: str
    title: str
    bullet_type: str
    scope: dict | None = None
    subject: str
    language: str
    question_type: str
    content: str
    rationale: str | None = None
    source_signals: list[dict] = Field(default_factory=list)
    helpful_count: int = 0
    harmful_count: int = 0
    confidence: float
    tags: list[str] = Field(default_factory=list)
    created_from: str | None = None
    review_status: str | None = None
    version: int
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ReflectionCandidateResponse(BaseModel):
    id: str
    status: str
    category: str
    subject: str
    language: str
    question_type: str
    scope: dict | None = None
    evidence: dict | None = None
    proposed_title: str
    proposed_bullet_type: str
    proposed_bullet_text: str
    rationale: str | None = None
    source_event_ids: list[str] = Field(default_factory=list)
    source_eval_sample_ids: list[str] = Field(default_factory=list)
    confidence: float
    merge_key: str
    review_notes: str | None = None
    promoted_bullet_id: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    reviewed_at: datetime | None = None


class CountItem(BaseModel):
    name: str
    count: int


class PlaybookOverviewResponse(BaseModel):
    retrieval_mode: str
    retrieval_limit: int
    feedback_event_count: int
    approved_bullet_count: int
    candidate_bullet_count: int
    archived_bullet_count: int
    reflection_candidate_count: int
    promoted_candidate_count: int
    warmup_exam_case_count: int
    warmup_question_case_count: int
    warmup_feedback_case_count: int
    top_feedback_categories: list[CountItem] = Field(default_factory=list)
    recent_bullets: list[PlaybookBulletResponse] = Field(default_factory=list)
    recent_candidates: list[ReflectionCandidateResponse] = Field(default_factory=list)
    last_reflection_run_at: datetime | None = None
