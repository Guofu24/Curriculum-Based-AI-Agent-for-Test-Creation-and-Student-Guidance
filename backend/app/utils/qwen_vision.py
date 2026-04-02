"""
Qwen Vision Client — tích hợp Qwen/Qwen3.5-9B self-hosted trên Kaggle/ngrok.

Endpoint tương thích OpenAI Chat Completions:
  POST /v1/chat/completions

Health check:
  GET  /health  → {"ok": true, "model": "Qwen/Qwen3.5-9B", ...}

Ưu tiên dùng cho:
1. OCR công thức / ký tự đặc biệt từ ảnh (thay Mathpix)
2. Mô tả nội dung ảnh trong tài liệu (thay GPT-4o Vision)
"""

import base64
import logging
from typing import Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class QwenVisionError(Exception):
    """Raised when Qwen vision call fails."""
    pass


class QwenVisionClient:
    """
    Client gọi Qwen/Qwen3.5-9B vision endpoint (tương thích OpenAI format).

    Base URL đọc từ QWEN_VISION_BASE_URL trong .env.
    Timeout cao hơn vì model chạy trên Kaggle / ngrok (có thể chậm).
    """

    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.QWEN_VISION_BASE_URL.rstrip("/")
        self._timeout = s.QWEN_VISION_TIMEOUT
        self._enabled = bool(self._base_url)

    async def health_check(self) -> bool:
        """Kiểm tra service còn sống không. Trả về True nếu ok."""
        if not self._enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                data = resp.json()
                return bool(data.get("ok"))
        except Exception as e:
            logger.warning("Qwen vision health check failed: %s", e)
            return False

    async def chat_with_image(
        self,
        prompt: str,
        image_bytes: bytes,
        image_media_type: str = "image/png",
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        """
        Gửi ảnh + prompt tới Qwen vision endpoint.

        Trả về nội dung text từ choices[0].message.content.
        Raise QwenVisionError nếu gọi thất bại.
        """
        if not self._enabled:
            raise QwenVisionError("Qwen vision is not configured (QWEN_VISION_BASE_URL is empty).")

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "model": "Qwen/Qwen3.5-9B",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_media_type};base64,{b64}"
                            },
                        },
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip() if content else ""
        except httpx.HTTPStatusError as e:
            raise QwenVisionError(
                f"Qwen vision HTTP error {e.response.status_code}: {e.response.text[:200]}"
            ) from e
        except Exception as e:
            raise QwenVisionError(f"Qwen vision call failed: {e}") from e

    async def extract_formula_from_image(self, image_bytes: bytes) -> Optional[str]:
        """
        Dùng Qwen để OCR công thức / ký tự toán học từ ảnh.
        Trả về LaTeX string, hoặc None nếu không phát hiện được.
        """
        prompt = (
            "You are a LaTeX OCR assistant. "
            "Look at this image and extract ALL mathematical formulas, equations, "
            "or special characters you see. "
            "Return ONLY the LaTeX representation, nothing else. "
            "If there are multiple formulas, separate them with newlines. "
            "If there's no math content, return an empty string."
        )
        try:
            result = await self.chat_with_image(
                prompt=prompt,
                image_bytes=image_bytes,
                max_tokens=512,
                temperature=0.05,
            )
            return result if result else None
        except QwenVisionError:
            return None

    async def describe_image(self, image_bytes: bytes, context: str = "") -> str:
        """
        Dùng Qwen để mô tả nội dung ảnh trong tài liệu giáo khoa.
        Trả về text mô tả, hoặc "" nếu thất bại.
        """
        context_hint = f"\nContext từ tài liệu: {context[:200]}" if context else ""
        prompt = (
            "Bạn là assistant mô tả hình ảnh trong sách giáo khoa tiếng Việt. "
            "Mô tả hình ảnh một cách chính xác, bao gồm: "
            "loại hình (đồ thị, sơ đồ, hình minh họa, bảng, ...), "
            "các đại lượng / ký hiệu có trong hình, "
            "và nội dung cần truyền đạt một cách ngắn gọn. "
            "Trả về text thuần, không dùng markdown."
            + context_hint
        )
        try:
            return await self.chat_with_image(
                prompt=prompt,
                image_bytes=image_bytes,
                max_tokens=512,
                temperature=0.3,
            )
        except QwenVisionError as e:
            logger.warning("Qwen describe_image failed: %s", e)
            return ""


# ── Singleton ──────────────────────────────────────────────────────────────────

_qwen_client: QwenVisionClient | None = None


def get_qwen_vision_client() -> QwenVisionClient:
    """Return singleton QwenVisionClient."""
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = QwenVisionClient()
    return _qwen_client
