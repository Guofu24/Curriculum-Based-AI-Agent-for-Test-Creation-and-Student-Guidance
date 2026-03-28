"""Bloom's Taxonomy classifier skill."""

import json
from pydantic import BaseModel
from typing import Literal
from app.agents.llm import get_llm_client


class BloomClassifierSkill:
    """
    Classifies a question's Bloom's Taxonomy level.

    Bloom Rubric:
    - Nhận biết (Knowledge): Định nghĩa, liệt kê, nêu tên
    - Thông hiểu (Comprehension): Giải thích, so sánh, phân biệt, áp dụng công thức 1 bước
    - Vận dụng (Application): Tính toán 2-3 bước, có điều kiện
    - Vận dụng cao (Analysis/Evaluation): Phân tích, đánh giá, bài toán phức hợp
    """

    BLOOM_RUBRIC = """Bạn là chuyên gia phân loại câu hỏi theo Bloom's Taxonomy cho môn học phổ thông Việt Nam.

Với mỗi câu hỏi, phân loại vào 1 trong 4 mức:

1. **nhan_biet** (Nhận biết - Knowledge):
   - Từ khóa: định nghĩa, liệt kê, nêu tên, cho biết, kể tên, trình bày
   - Đặc điểm: hỏi thẳng khái niệm/công thức đã học
   - Ví dụ: "Định luật 2 Newton được phát biểu là gì?"

2. **thong_hieu** (Thông hiểu - Comprehension):
   - Từ khóa: giải thích, so sánh, phân biệt, mô tả, áp dụng công thức 1 bước
   - Đặc điểm: áp dụng công thức đơn giản, trực tiếp
   - Ví dụ: "Một vật chịu lực F=10N, khối lượng m=2kg. Tính gia tốc."

3. **van_dung** (Vận dụng - Application):
   - Từ khóa: tính toán, giải bài toán, xác định, vận dụng
   - Đặc điểm: bài toán 2-3 bước, có điều kiện, cần suy luận
   - Ví dụ: "Một vật trượt trên mặt phẳng nghiêng 30 độ. Tính gia tốc biết hệ số ma sát μ=0.2."

4. **van_dung_cao** (Vận dụng cao - Analysis/Evaluation):
   - Từ khóa: phân tích, đánh giá, thiết kế, so sánh và nhận xét, bài toán phức hợp
   - Đặc điểm: nhiều công thức kết hợp, số liệu thực tế, câu hỏi mở
   - Ví dụ: "Hai vật A và B nối bằng sợi dây qua ròng rọc. Vật A trượt trên mặt phẳng nghiêng, vật B treo. Phân tích chuyển động của hệ và tính gia tốc."

Trả về JSON:
{
  "bloom_level": "nhan_biet|thong_hieu|van_dung|van_dung_cao",
  "confidence": 0.0-1.0,
  "reasoning": "Giải thích ngắn tại sao chọn mức này"
}"""

    async def classify(
        self,
        question_stem: str,
        question_type: Literal["mcq", "essay"] = "mcq",
        subject: str = "general",
    ) -> dict:
        """Classify a question's Bloom level."""
        client = get_llm_client()

        user_content = f"Câu hỏi: {question_stem}\nLoại: {question_type}\nMôn: {subject}"

        messages = [
            {"role": "system", "content": self.BLOOM_RUBRIC},
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
                "bloom_level": result.get("bloom_level", "thong_hieu"),
                "confidence": float(result.get("confidence", 0.5)),
                "reasoning": result.get("reasoning", ""),
            }

        except Exception as e:
            # Fallback: simple keyword matching
            return self._fallback_classify(question_stem)

    def _fallback_classify(self, question_stem: str) -> dict:
        """Fallback keyword-based classification."""
        stem_lower = question_stem.lower()

        # van_dung_cao keywords
        high_keywords = ["phân tích", "đánh giá", "so sánh và nhận xét", "thiết kế",
                         "nhiều công thức", "hệ vật", "tổng hợp"]
        if any(kw in stem_lower for kw in high_keywords):
            return {"bloom_level": "van_dung_cao", "confidence": 0.6, "reasoning": "Keyword match"}

        # van_dung keywords
        app_keywords = ["tính toán", "giải", "xác định", "vận dụng", "bài toán",
                       "chuyển động", "tìm", "cho biết"]
        if any(kw in stem_lower for kw in app_keywords):
            return {"bloom_level": "van_dung", "confidence": 0.5, "reasoning": "Keyword match"}

        # thong_hieu keywords
        comp_keywords = ["giải thích", "so sánh", "phân biệt", "mô tả", "áp dụng công thức"]
        if any(kw in stem_lower for kw in comp_keywords):
            return {"bloom_level": "thong_hieu", "confidence": 0.5, "reasoning": "Keyword match"}

        return {"bloom_level": "nhan_biet", "confidence": 0.4, "reasoning": "Default fallback"}
