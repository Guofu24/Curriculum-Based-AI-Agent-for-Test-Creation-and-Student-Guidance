"""Difficulty estimator skill."""

import json
from typing import Literal, Optional
from app.agents.llm import get_llm_client
from app.observability.tracer import get_tracer


# G15 Fix: default solution_steps mapped from bloom_level
BLOOM_SOLUTION_STEPS = {
    "nhan_biet": 1,
    "thong_hieu": 2,
    "van_dung": 3,
    "van_dung_cao": 5,
}


class DifficultyEstimatorSkill:
    """
    Estimates the difficulty score of a question.
    Score: 0.0 (very easy) to 1.0 (very hard).
    Also estimates solve time.
    """

    DIFFICULTY_PROMPT = """Bạn là chuyên gia ước lượng độ khó câu hỏi.

Với mỗi câu hỏi, ước lượng:
1. **difficulty_score**: 0.0-1.0
   - 0.0-0.2: Rất dễ (hỏi thẳng định nghĩa)
   - 0.3-0.4: Dễ (áp dụng 1 công thức)
   - 0.5-0.6: Trung bình (2 bước tính toán)
   - 0.7-0.8: Khó (nhiều bước, có điều kiện)
   - 0.9-1.0: Rất khó (phân tích phức hợp, nhiều công thức)

2. **estimated_solve_time_minutes**: Thời gian giải ước tính (phút)

3. **complexity_factors**: Các yếu tố phức tạp
   - "multi_formula": Nhiều công thức kết hợp
   - "conditional": Có điều kiện ràng buộc
   - "requires_calculus": Cần vi phân/tích phân
   - "real_world_data": Dữ liệu thực tế phức tạp
   - "conceptual_deep": Cần hiểu sâu khái niệm

Trả về JSON:
{
  "difficulty_score": 0.0-1.0,
  "estimated_solve_time_minutes": số phút,
  "complexity_factors": ["list of factors"]
}"""

    @get_tracer().skill_span("difficulty_estimator")
    async def estimate(
        self,
        question_stem: str,
        bloom_level: Literal["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"] = "thong_hieu",
        solution_steps: Optional[int] = None,
    ) -> dict:
        """Estimate difficulty of a question.

        G15 Fix: solution_steps defaults to BLOOM_SOLUTION_STEPS
        if not explicitly provided.
        """
        # G15 Fix: apply default from bloom_level when solution_steps is None
        if solution_steps is None:
            solution_steps = BLOOM_SOLUTION_STEPS.get(bloom_level, 2)

        client = get_llm_client()

        user_content = f"""Câu hỏi: {question_stem}
Bloom level: {bloom_level}
Số bước giải: {solution_steps}"""

        messages = [
            {"role": "system", "content": self.DIFFICULTY_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            response = await client.chat(
                messages=messages,
                role="skills",
                max_tokens=200,
                temperature=0.1,
            )

            result = json.loads(response)

            return {
                "difficulty_score": float(result.get("difficulty_score", 0.5)),
                "estimated_solve_time_minutes": int(result.get("estimated_solve_time_minutes", 5)),
                "complexity_factors": result.get("complexity_factors", []),
            }

        except Exception:
            return self._fallback_estimate(bloom_level, solution_steps)

    def _fallback_estimate(
        self,
        bloom_level: str,
        solution_steps: Optional[int],
    ) -> dict:
        """Fallback estimation based on Bloom level."""
        bloom_to_difficulty = {
            "nhan_biet": (0.15, 2),
            "thong_hieu": (0.30, 5),
            "van_dung": (0.60, 10),
            "van_dung_cao": (0.85, 15),
        }

        score, time = bloom_to_difficulty.get(bloom_level, (0.5, 5))

        if solution_steps is not None:
            time = min(solution_steps * 3, 30)

        return {
            "difficulty_score": score,
            "estimated_solve_time_minutes": time,
            "complexity_factors": [],
        }

    async def run(
        self,
        question_stem: str,
        bloom_level: Literal["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"] = "thong_hieu",
        solution_steps: Optional[int] = None,
    ) -> dict:
        """Alias for estimate() to match skill interface."""
        return await self.estimate(question_stem, bloom_level, solution_steps)
