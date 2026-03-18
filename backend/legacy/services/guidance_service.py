"""
Guidance Service — Student guidance and mastery profile management.

Handles:
  - Recording student submissions
  - Auto-grading MCQ answers
  - Computing mastery profiles
  - Generating personalized guidance (via Guidance Agent)

Spec reference: §6.16 — Student Guidance Pipeline
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.student import MasteryProfile, StudentSubmission

logger = logging.getLogger(__name__)


class GuidanceService:
    """Service for student guidance operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ──────────────────────────────────────────
    # Submissions
    # ──────────────────────────────────────────

    async def create_submission(
        self,
        student_id: str,
        exam_id: str,
        answers: list[dict],
        exam_version_id: Optional[str] = None,
    ) -> StudentSubmission:
        """Create a new student submission."""
        submission = StudentSubmission(
            student_id=student_id,
            exam_id=exam_id,
            exam_version_id=exam_version_id,
            answers_json=answers,
            status="submitted",
            submitted_at=datetime.utcnow(),
        )
        self.db.add(submission)
        await self.db.commit()
        await self.db.refresh(submission)

        logger.info(
            f"[GUIDANCE] Created submission {submission.id} "
            f"for student {student_id} on exam {exam_id}"
        )
        return submission

    async def get_submission(self, submission_id: str) -> Optional[StudentSubmission]:
        """Get a submission by ID."""
        result = await self.db.execute(
            select(StudentSubmission).where(StudentSubmission.id == submission_id)
        )
        return result.scalar_one_or_none()

    async def get_student_submissions(
        self, student_id: str, exam_id: Optional[str] = None
    ) -> list[StudentSubmission]:
        """Get all submissions for a student, optionally filtered by exam."""
        query = select(StudentSubmission).where(
            StudentSubmission.student_id == student_id
        )
        if exam_id:
            query = query.where(StudentSubmission.exam_id == exam_id)
        query = query.order_by(StudentSubmission.submitted_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ──────────────────────────────────────────
    # Auto-Grading (MCQ)
    # ──────────────────────────────────────────

    async def auto_grade(
        self,
        submission_id: str,
        exam_questions: list[dict],
    ) -> StudentSubmission:
        """
        Auto-grade MCQ questions in a submission.

        Compares student answers against correct answers from exam_questions.
        Essay questions are marked for manual grading.
        """
        submission = await self.get_submission(submission_id)
        if not submission:
            raise ValueError(f"Submission {submission_id} not found")

        answers = submission.answers_json or []
        question_map = {q["id"]: q for q in exam_questions}

        total_score = 0.0
        max_score = 0.0
        analysis = []

        for answer in answers:
            question_id = answer.get("question_id")
            student_answer = answer.get("answer", "")
            question = question_map.get(question_id, {})

            q_type = question.get("question_type", "mcq")
            correct_answer = question.get("correct_answer", "")
            bloom_level = question.get("bloom_level", "remember")
            scope_tags = question.get("scope_tags", [])

            if q_type == "mcq":
                is_correct = student_answer.strip().upper() == correct_answer.strip().upper()
                score = 1.0 if is_correct else 0.0
                max_score += 1.0
                total_score += score

                analysis.append({
                    "question_id": question_id,
                    "bloom_level": bloom_level,
                    "scope_tags": scope_tags,
                    "is_correct": is_correct,
                    "score": score,
                    "mastery_signal": "strong" if is_correct else "weak",
                })
            else:
                # Essay — mark for manual grading
                max_score += 1.0
                analysis.append({
                    "question_id": question_id,
                    "bloom_level": bloom_level,
                    "scope_tags": scope_tags,
                    "is_correct": None,
                    "score": None,
                    "mastery_signal": "pending",
                })

        submission.total_score = total_score
        submission.max_possible_score = max_score
        submission.auto_graded = True
        submission.question_analysis_json = analysis
        submission.graded_at = datetime.utcnow()
        submission.status = "graded"

        await self.db.commit()
        await self.db.refresh(submission)

        logger.info(
            f"[GUIDANCE] Auto-graded submission {submission_id}: "
            f"{total_score}/{max_score}"
        )
        return submission

    # ──────────────────────────────────────────
    # Mastery Profiles
    # ──────────────────────────────────────────

    async def get_mastery_profile(
        self, student_id: str
    ) -> list[MasteryProfile]:
        """Get all mastery profile entries for a student."""
        result = await self.db.execute(
            select(MasteryProfile)
            .where(MasteryProfile.student_id == student_id)
            .order_by(MasteryProfile.chapter_number)
        )
        return list(result.scalars().all())

    async def update_mastery_from_submission(
        self,
        student_id: str,
        submission: StudentSubmission,
    ) -> list[MasteryProfile]:
        """
        Update mastery profiles based on a graded submission.

        For each scope unit in the submission's question analysis,
        update (or create) the corresponding mastery profile entry.
        """
        analysis = submission.question_analysis_json or []
        updated_scopes: dict[str, dict] = {}

        for item in analysis:
            if item.get("mastery_signal") == "pending":
                continue

            for scope_tag in item.get("scope_tags", []):
                if scope_tag not in updated_scopes:
                    updated_scopes[scope_tag] = {
                        "correct": 0,
                        "total": 0,
                        "bloom_scores": {},
                    }

                scope_data = updated_scopes[scope_tag]
                scope_data["total"] += 1
                if item.get("is_correct"):
                    scope_data["correct"] += 1

                bloom = item.get("bloom_level", "remember")
                if bloom not in scope_data["bloom_scores"]:
                    scope_data["bloom_scores"][bloom] = {"correct": 0, "total": 0}
                scope_data["bloom_scores"][bloom]["total"] += 1
                if item.get("is_correct"):
                    scope_data["bloom_scores"][bloom]["correct"] += 1

        profiles = []
        for scope_id, data in updated_scopes.items():
            # Find or create profile
            result = await self.db.execute(
                select(MasteryProfile).where(
                    MasteryProfile.student_id == student_id,
                    MasteryProfile.scope_id == scope_id,
                )
            )
            profile = result.scalar_one_or_none()

            if not profile:
                profile = MasteryProfile(
                    student_id=student_id,
                    scope_id=scope_id,
                    scope_type="chapter" if scope_id.startswith("chapter:") else "topic",
                )
                self.db.add(profile)

            # Update counts
            profile.total_count = (profile.total_count or 0) + data["total"]
            profile.correct_count = (profile.correct_count or 0) + data["correct"]
            profile.total_attempts = (profile.total_attempts or 0) + 1
            profile.overall_mastery = profile.correct_count / max(profile.total_count, 1)

            # Update Bloom mastery
            bloom_mastery = dict(profile.bloom_mastery_json or {})
            for bloom, scores in data["bloom_scores"].items():
                if bloom not in bloom_mastery:
                    bloom_mastery[bloom] = {"correct": 0, "total": 0, "mastery": 0.0}
                bloom_mastery[bloom]["correct"] += scores["correct"]
                bloom_mastery[bloom]["total"] += scores["total"]
                bloom_mastery[bloom]["mastery"] = (
                    bloom_mastery[bloom]["correct"] / max(bloom_mastery[bloom]["total"], 1)
                )
            profile.bloom_mastery_json = bloom_mastery

            # Update trend
            trend = list(profile.trend_json or [])
            trend.append({
                "date": datetime.utcnow().isoformat(),
                "score": data["correct"] / max(data["total"], 1),
                "exam_id": submission.exam_id,
            })
            profile.trend_json = trend[-20:]  # Keep last 20 entries
            profile.last_exam_id = submission.exam_id

            profiles.append(profile)

        await self.db.commit()
        logger.info(
            f"[GUIDANCE] Updated {len(profiles)} mastery profiles for student {student_id}"
        )
        return profiles

    # ──────────────────────────────────────────
    # Guidance Generation (Stub for AI agent)
    # ──────────────────────────────────────────

    async def generate_guidance(
        self,
        submission_id: str,
    ) -> dict:
        """
        Generate personalized guidance for a student submission.

        TODO: Integrate with Guidance Agent for AI-powered analysis.
        Currently returns a structured summary based on question analysis.
        """
        submission = await self.get_submission(submission_id)
        if not submission:
            raise ValueError(f"Submission {submission_id} not found")

        analysis = submission.question_analysis_json or []
        weak_topics = []
        strong_topics = []

        # Aggregate by scope
        scope_results: dict[str, dict] = {}
        for item in analysis:
            for tag in item.get("scope_tags", []):
                if tag not in scope_results:
                    scope_results[tag] = {"correct": 0, "total": 0}
                scope_results[tag]["total"] += 1
                if item.get("is_correct"):
                    scope_results[tag]["correct"] += 1

        for scope_id, data in scope_results.items():
            mastery = data["correct"] / max(data["total"], 1)
            entry = {
                "scope_id": scope_id,
                "mastery_level": round(mastery, 2),
                "correct": data["correct"],
                "total": data["total"],
            }
            if mastery < 0.6:
                entry["recommendation"] = "Cần ôn tập lại phần này"
                weak_topics.append(entry)
            else:
                entry["recommendation"] = "Nắm vững phần này"
                strong_topics.append(entry)

        guidance = {
            "submission_id": submission_id,
            "total_score": submission.total_score,
            "max_score": submission.max_possible_score,
            "percentage": round(
                (submission.total_score or 0) / max(submission.max_possible_score or 1, 1) * 100, 1
            ),
            "weak_topics": weak_topics,
            "strong_topics": strong_topics,
            "overall_recommendation": (
                "Cần ôn tập thêm" if len(weak_topics) > len(strong_topics)
                else "Kết quả tốt, tiếp tục giữ vững"
            ),
        }

        # Persist guidance
        submission.weak_topics_json = weak_topics
        submission.strong_topics_json = strong_topics
        submission.guidance_json = guidance
        await self.db.commit()

        return guidance
