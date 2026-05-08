"""Bloom's Taxonomy classifier skill."""

import json
from typing import Literal
from app.agents.llm import get_llm_client
from app.observability.tracer import get_tracer


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

    # Few-shot examples (1 per Bloom level) — real Vietnamese physics questions
    # Purpose: anchor cognitive-level pattern, NOT topic content
    FEW_SHOT_EXAMPLES = [
        (
            "Khi xịt nước hoa ở một góc của căn phòng thì ta vẫn ngửi được hương thơm ở một vị trí khác, vì "
            "A. quạt máy thổi hương thơm bay xa hơn. B. nồng độ hương thơm trong lọ quá nhiều. "
            "C. khi xịt nước hoa ra khỏi lọ, nước hoa sẽ ở thể hơi nên các hạt chuyển động tự do khắp căn phòng. "
            "D. Tất cả các ý trên đều sai.",
            "mcq",
            '{"bloom_level":"nhan_biet","confidence":0.95,"reasoning":"Câu hỏi nhận biết hiện tượng khuếch tán — chỉ cần nhớ lại kiến thức về chuyển động phân tử khí, không yêu cầu suy luận hay tính toán"}',
        ),
        (
            "Coi tia sét là dòng các electron chuyển động gần như thẳng đứng từ đám mây xuống mặt đất. "
            "Biết thành phần nằm ngang của từ trường Trái Đất hướng về phía Bắc. "
            "Do tác dụng của từ trường Trái Đất, tia sét có xu hướng lệch theo hướng nào? A. Bắc. B. Tây. C. Đông. D. Nam.",
            "mcq",
            '{"bloom_level":"thong_hieu","confidence":0.90,"reasoning":"Yêu cầu áp dụng quy tắc lực Lorentz để xác định hướng lệch — hiểu bản chất lực từ tác dụng lên dòng điện, không tính toán số cụ thể"}',
        ),
        (
            "Một phân tử khí lí tưởng đang chuyển động qua tâm một bình cầu có đường kính d = 0,10 m. "
            "Trong mỗi giây, phân tử này va chạm vào thành bình cầu 4000 lần. "
            "Coi rằng phân tử này chỉ va chạm với thành bình và tốc độ của phân tử là không đổi sau mỗi va chạm. "
            "Tốc độ chuyển động trung bình của phân tử khí trong bình là bao nhiêu m/s?",
            "short_answer",
            '{"bloom_level":"thong_hieu","confidence":0.88,"reasoning":"Tính tốc độ bằng 1 bước: v = 2d × n = 2×0,1×4000 = 800 m/s — áp dụng trực tiếp định nghĩa tốc độ, không có ẩn số trung gian"}',
        ),
        (
            "Một lò phản ứng hạt nhân sử dụng uranium 235U, thanh nhiên liệu làm giàu đến 4%. "
            "Mỗi hạt nhân 235U phân hạch tỏa ra năng lượng trung bình 200 MeV. "
            "Khi khối lượng 235U còn lại 99,5% so với ban đầu thì 500 tấn nước làm mát tăng từ 30°C lên 250°C. "
            "Biết 90% năng lượng dùng để làm nóng nước, nhiệt dung riêng nước 4200 J/kg.K, 1 MeV = 1,6×10⁻¹³ J. "
            "Khối lượng các thanh nhiên liệu ban đầu là bao nhiêu kg?",
            "short_answer",
            '{"bloom_level":"van_dung","confidence":0.92,"reasoning":"Cần tính tuần tự qua 4 bước trung gian: nhiệt lượng nước hấp thụ → năng lượng U-235 giải phóng → số hạt phân hạch → khối lượng U-235 → khối lượng thanh nhiên liệu. Có ẩn số trung gian rõ ràng"}',
        ),
        (
            "Ba chất điểm không thẳng hàng P1, P2, P3 có khối lượng m1, m2, m3 tương tác hấp dẫn với nhau. "
            "Gọi T là trục đi qua khối tâm và vuông góc với mặt phẳng tam giác P1P2P3. "
            "Các khoảng cách d12, d23, d13 và vận tốc góc ω quanh trục T phải thỏa mãn hệ thức gì "
            "để dạng tam giác P1P2P3 không đổi khi hệ chuyển động?",
            "essay",
            '{"bloom_level":"van_dung_cao","confidence":0.95,"reasoning":"Bài toán 3 vật hấp dẫn yêu cầu thiết lập phương trình Newton cho từng chất điểm, kết hợp định luật hấp dẫn và điều kiện hình học để tìm ràng buộc — phân tích hệ phức hợp đa định luật, không có đáp số số"}',
        ),
        (
            "Trái Đất chuyển động quanh Mặt Trời theo quỹ đạo tròn bán kính RT với chu kỳ T0 và vận tốc vT. "
            "Một sao chổi chuyển động trong mặt phẳng quỹ đạo Trái Đất, đi gần Mặt Trời nhất ở khoảng cách kRT với vận tốc v1. "
            "1. Xác định vận tốc v của sao chổi khi cắt quỹ đạo Trái Đất. "
            "2. Chứng minh quỹ đạo sao chổi là elip, xác định bán trục lớn a = λRT và tâm sai e, chu kỳ T = nT0. "
            "3. Tính khoảng thời gian τ sao chổi còn ở bên trong quỹ đạo Trái Đất dưới dạng tích phân và tính gần đúng.",
            "essay",
            '{"bloom_level":"van_dung_cao","confidence":0.96,"reasoning":"Kết hợp bảo toàn momen động lượng và năng lượng để tìm vận tốc, chứng minh quỹ đạo elip bằng phân tích hình học quỹ đạo, sau đó tính tích phân thời gian — đa công cụ, đa bước, yêu cầu chứng minh lý thuyết"}',
        ),
    ]

    @get_tracer().skill_span("bloom_classifier")
    async def classify(
        self,
        question_stem: str,
        question_type: Literal["mcq", "essay"] = "mcq",
        subject: str = "general",
    ) -> dict:
        """Classify a question's Bloom level."""
        client = get_llm_client()

        user_content = f"Câu hỏi: {question_stem}\nLoại: {question_type}\nMôn: {subject}"

        # Build messages with few-shot examples before the real input
        messages: list[dict] = [{"role": "system", "content": self.BLOOM_RUBRIC}]
        for stem, q_type, expected_output in self.FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": f"Câu hỏi: {stem}\nLoại: {q_type}\nMôn: vật lý"})
            messages.append({"role": "assistant", "content": expected_output})
        messages.append({"role": "user", "content": user_content})

        try:
            response = await client.chat(
                messages=messages,
                role="skills",
                max_tokens=300,
                temperature=0.1,
            )

            result = json.loads(response)

            return {
                "bloom_level": result.get("bloom_level", "thong_hieu"),
                "confidence": float(result.get("confidence", 0.5)),
                "reasoning": result.get("reasoning", ""),
            }

        except Exception as e:
            return self._fallback_classify(question_stem)

    def _fallback_classify(self, question_stem: str) -> dict:
        """Fallback keyword-based classification."""
        stem_lower = question_stem.lower()

        high_keywords = ["phân tích", "đánh giá", "so sánh và nhận xét", "thiết kế",
                         "nhiều công thức", "hệ vật", "tổng hợp"]
        if any(kw in stem_lower for kw in high_keywords):
            return {"bloom_level": "van_dung_cao", "confidence": 0.6, "reasoning": "Keyword match"}

        app_keywords = ["tính toán", "giải", "xác định", "vận dụng", "bài toán",
                       "chuyển động", "tìm", "cho biết"]
        if any(kw in stem_lower for kw in app_keywords):
            return {"bloom_level": "van_dung", "confidence": 0.5, "reasoning": "Keyword match"}

        comp_keywords = ["giải thích", "so sánh", "phân biệt", "mô tả", "áp dụng công thức"]
        if any(kw in stem_lower for kw in comp_keywords):
            return {"bloom_level": "thong_hieu", "confidence": 0.5, "reasoning": "Keyword match"}

        return {"bloom_level": "nhan_biet", "confidence": 0.4, "reasoning": "Default fallback"}

    async def run(
        self,
        question_stem: str,
        question_type: Literal["mcq", "essay"] = "mcq",
        subject: str = "general",
    ) -> dict:
        """Alias for classify() to match skill interface."""
        return await self.classify(question_stem, question_type, subject)
