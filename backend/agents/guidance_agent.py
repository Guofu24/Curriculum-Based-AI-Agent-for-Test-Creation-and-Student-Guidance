"""
Guidance Agent — AI-powered personalized student guidance.

Analyzes student submission results and mastery profiles to generate
personalized study recommendations, practice questions, and learning paths.

Spec reference: §6.16 — Student Guidance Pipeline

NOTE: This is a foundation implementation. Full AI-powered analysis
will be integrated in a future phase using the RAG pipeline to reference
original textbook content for targeted recommendations.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class GuidanceRecommendation:
    """A single study recommendation for a student."""
    scope_id: str
    scope_title: str = ""
    priority: int = 0  # 1 = highest priority
    mastery_level: float = 0.0
    weak_bloom_levels: list[str] = field(default_factory=list)
    recommendation_text: str = ""
    suggested_topics: list[str] = field(default_factory=list)
    practice_question_types: list[str] = field(default_factory=list)


@dataclass
class StudentGuidanceReport:
    """Complete guidance report for a student."""
    student_id: str
    overall_mastery: float = 0.0
    total_exams_taken: int = 0
    recommendations: list[GuidanceRecommendation] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    generated_practice_quiz: Optional[dict] = None


class GuidanceAgent:
    """
    Agent that generates personalized study guidance.

    Pipeline:
    1. Analyze mastery profiles to identify weak areas
    2. Prioritize topics by weakness severity + recency
    3. Generate recommendations with specific study actions
    4. Optionally generate practice quiz targeting weak areas

    Future enhancements:
    - RAG-powered topic summaries from textbook content
    - LLM-generated personalized study plans
    - Adaptive practice quiz generation
    """

    def __init__(self, llm=None):
        self.llm = llm

    async def generate_report(
        self,
        student_id: str,
        mastery_profiles: list[dict],
        recent_submissions: list[dict] | None = None,
    ) -> StudentGuidanceReport:
        """
        Generate a complete guidance report for a student.

        Args:
            student_id: The student's user ID
            mastery_profiles: List of mastery profile dicts
            recent_submissions: Recent submission data for trend analysis
        """
        report = StudentGuidanceReport(student_id=student_id)

        if not mastery_profiles:
            report.next_steps = ["Hoàn thành bài kiểm tra đầu tiên để nhận đánh giá"]
            return report

        # ── Compute overall mastery ──
        total_mastery = sum(p.get("overall_mastery", 0) for p in mastery_profiles)
        report.overall_mastery = total_mastery / max(len(mastery_profiles), 1)
        report.total_exams_taken = sum(p.get("total_attempts", 0) for p in mastery_profiles)

        # ── Identify strengths and weaknesses ──
        for profile in mastery_profiles:
            mastery = profile.get("overall_mastery", 0)
            title = profile.get("scope_title") or profile.get("scope_id", "Unknown")

            if mastery >= 0.8:
                report.strengths.append(title)
            elif mastery < 0.6:
                report.weaknesses.append(title)

                # Analyze Bloom-level weaknesses
                bloom_mastery = profile.get("bloom_mastery_json", {})
                weak_blooms = [
                    level for level, data in bloom_mastery.items()
                    if isinstance(data, dict) and data.get("mastery", 1.0) < 0.5
                ]

                recommendation = GuidanceRecommendation(
                    scope_id=profile.get("scope_id", ""),
                    scope_title=title,
                    mastery_level=mastery,
                    weak_bloom_levels=weak_blooms,
                    priority=1 if mastery < 0.3 else 2 if mastery < 0.5 else 3,
                )

                # Generate specific recommendations
                if weak_blooms:
                    bloom_labels = {
                        "remember": "ghi nhớ",
                        "understand": "hiểu",
                        "apply": "vận dụng",
                        "analyze": "phân tích",
                        "evaluate": "đánh giá",
                        "create": "sáng tạo",
                    }
                    weak_bloom_text = ", ".join(
                        bloom_labels.get(b, b) for b in weak_blooms
                    )
                    recommendation.recommendation_text = (
                        f"Cần ôn tập '{title}' — yếu ở mức {weak_bloom_text}. "
                        f"Tỷ lệ đúng hiện tại: {mastery:.0%}."
                    )
                else:
                    recommendation.recommendation_text = (
                        f"Cần ôn tập thêm '{title}'. Tỷ lệ đúng: {mastery:.0%}."
                    )

                report.recommendations.append(recommendation)

        # Sort recommendations by priority
        report.recommendations.sort(key=lambda r: r.priority)

        # ── Next steps ──
        if report.weaknesses:
            report.next_steps.append(
                f"Ôn tập lại {len(report.weaknesses)} chủ đề yếu: "
                + ", ".join(report.weaknesses[:3])
            )
        if report.strengths:
            report.next_steps.append(
                f"Giữ vững {len(report.strengths)} chủ đề mạnh"
            )
        if report.overall_mastery < 0.7:
            report.next_steps.append("Làm thêm bài tập để nâng cao kiến thức")

        logger.info(
            f"[GUIDANCE_AGENT] Generated report for student {student_id}: "
            f"mastery={report.overall_mastery:.0%}, "
            f"{len(report.recommendations)} recommendations"
        )

        return report
