"""Scope checker skill - verifies questions are within the selected scope."""

import json
from pydantic import BaseModel
from typing import Literal
from app.agents.llm import get_llm_client


class ScopeCheckerSkill:
    """
    Verifies that a question is within the allowed scope.
    Compares question content against retrieved knowledge chunks.
    """

    SCOPE_CHECK_PROMPT = """Bạn là chuyên gia kiểm tra câu hỏi có nằm trong phạm vi kiến thức cho phép hay không.

Nhiệm vụ:
1. Đọc câu hỏi
2. Đọc các chunk kiến thức được phép (allowed content)
3. Kiểm tra xem câu hỏi có sử dụng kiến thức ngoài phạm vi không
4. Kiểm tra xem câu hỏi có bị hallucination (kiến thức không có trong tài liệu) không

Trả về JSON:
{
  "in_scope": true/false,
  "violation_type": null/"out_of_scope"|"hallucination",
  "evidence_chunk_ids": ["list of chunk IDs that support this question"],
  "confidence": 0.0-1.0,
  "reasoning": "Giải thích ngắn"
}"""

    async def check(
        self,
        question_stem: str,
        allowed_content: list[dict],
        scope_chapters: list[str],
    ) -> dict:
        """Check if a question is within scope."""
        if not allowed_content:
            return {
                "in_scope": True,
                "violation_type": None,
                "evidence_chunk_ids": [],
                "confidence": 0.0,
                "reasoning": "No content available to check",
            }

        client = get_llm_client()

        # Build content summary
        content_summary = "\n\n".join([
            f"[Chunk {chunk.get('chunk_id', 'unknown')}]: {chunk.get('content', '')[:300]}"
            for chunk in allowed_content[:10]  # Limit to 10 chunks
        ])

        scope_str = ", ".join(scope_chapters)

        user_content = f"""Câu hỏi cần kiểm tra:
{question_stem}

Phạm vi cho phép (chapters): {scope_str}

Kiến thức có sẵn (các chunk):
{content_summary}"""

        messages = [
            {"role": "system", "content": self.SCOPE_CHECK_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            response = await client.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=300,
            )

            result = json.loads(response.choices[0].message.content)

            return {
                "in_scope": result.get("in_scope", True),
                "violation_type": result.get("violation_type"),
                "evidence_chunk_ids": result.get("evidence_chunk_ids", []),
                "confidence": float(result.get("confidence", 0.5)),
                "reasoning": result.get("reasoning", ""),
            }

        except Exception as e:
            # Fallback: basic containment check
            return self._fallback_check(question_stem, allowed_content)

    def _fallback_check(self, question_stem: str, allowed_content: list[dict]) -> dict:
        """Fallback basic check - look for keyword matches."""
        stem_lower = question_stem.lower()

        matching_chunks = []
        for chunk in allowed_content:
            content_lower = chunk.get("content", "").lower()
            # Simple overlap check
            words = set(stem_lower.split()) & set(content_lower.split())
            if len(words) >= 3:
                matching_chunks.append(chunk.get("chunk_id", "unknown"))

        if matching_chunks:
            return {
                "in_scope": True,
                "violation_type": None,
                "evidence_chunk_ids": matching_chunks[:3],
                "confidence": 0.4,
                "reasoning": "Basic keyword overlap found",
            }

        return {
            "in_scope": False,
            "violation_type": "hallucination",
            "evidence_chunk_ids": [],
            "confidence": 0.3,
            "reasoning": "No matching content found (fallback)",
        }
