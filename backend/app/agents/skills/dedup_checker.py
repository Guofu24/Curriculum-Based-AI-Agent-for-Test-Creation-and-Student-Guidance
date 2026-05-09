"""Deduplication checker skill."""

import json
from pydantic import BaseModel
from app.agents.llm import get_llm_client
from app.observability.tracer import get_tracer


class DedupCheckerSkill:
    """
    Checks if a new question is too similar to existing questions.
    Uses topic/keyword overlap and LLM-based semantic comparison.
    """

    DEDUP_PROMPT = """Bạn là chuyên gia kiểm tra trùng lặp câu hỏi.

Nhiệm vụ:
1. So sánh câu hỏi mới với các câu hỏi đã có
2. Tính độ tương đồng về:
   - Chủ đề (topic)
   - Công thức/sách được sử dụng
   - Mức độ khó (Bloom level)
3. Xác định xem có phải là trùng lặp hay biến thể không

Trả về JSON:
{
  "is_duplicate": true/false,
  "duplicate_with": "tên câu hỏi bị trùng hoặc null",
  "similarity_score": 0.0-1.0,
  "suggestion": "Đề xuất: chuyển sang chủ đề khác hoặc null"
}"""

    @get_tracer().skill_span("dedup_checker")
    async def check(
        self,
        new_question_topic: str,
        existing_topics: list[str],
    ) -> dict:
        """Check if a question topic is too similar to existing ones."""
        if not existing_topics:
            return {
                "is_duplicate": False,
                "duplicate_with": None,
                "similarity_score": 0.0,
                "suggestion": None,
            }

        client = get_llm_client()

        topics_list = "\n".join([
            f"- {i+1}. {topic}" for i, topic in enumerate(existing_topics)
        ])

        user_content = f"""Câu hỏi mới:
{new_question_topic}

Các câu hỏi đã có:
{topics_list}"""

        messages = [
            {"role": "system", "content": self.DEDUP_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            response = await client.chat(
                messages=messages,
                role="skills",
                max_tokens=300,
                temperature=0.1,
            )

            result = json.loads(response)

            return {
                "is_duplicate": result.get("similarity_score", 0) >= 0.75,
                "duplicate_with": result.get("duplicate_with"),
                "similarity_score": float(result.get("similarity_score", 0)),
                "suggestion": result.get("suggestion"),
            }

        except Exception:
            return self._fallback_check(new_question_topic, existing_topics)

    def _fallback_check(self, new_topic: str, existing_topics: list[str]) -> dict:
        """Fallback keyword-based deduplication check."""
        new_words = set(new_topic.lower().split())

        for topic in existing_topics:
            existing_words = set(topic.lower().split())
            overlap = len(new_words & existing_words)
            total = len(new_words | existing_words)

            if total > 0:
                similarity = overlap / total

                if similarity >= 0.7:
                    return {
                        "is_duplicate": True,
                        "duplicate_with": topic,
                        "similarity_score": similarity,
                        "suggestion": f"Câu hỏi quá giống với '{topic}'. Thử chủ đề khác.",
                    }

        return {
            "is_duplicate": False,
            "duplicate_with": None,
            "similarity_score": 0.0,
            "suggestion": None,
        }

    async def run(
        self,
        new_question_topic: str,
        existing_topics: list[str],
    ) -> dict:
        """Local keyword overlap check — no LLM call to avoid 429."""
        return self._fallback_check(new_question_topic, existing_topics)
