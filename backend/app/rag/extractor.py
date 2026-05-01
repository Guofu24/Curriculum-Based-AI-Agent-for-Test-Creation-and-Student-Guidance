"""Formula and image extraction from document content.

Vision OCR priority:
1. Qwen/Qwen3.5-9B (self-hosted, configured via QWEN_VISION_BASE_URL)
2. MathPix API (optional fallback, configured via MATHPIX_APP_ID + MATHPIX_APP_KEY)
3. Nougat (local, placeholder)

Image description priority:
1. Qwen/Qwen3.5-9B vision endpoint
2. LLMClient.chat_vision() (existing GPT-4o / Groq vision fallback)
"""

import re
import base64
from typing import Literal, Optional
from dataclasses import dataclass


@dataclass
class FormulaInfo:
    """Information about a detected formula."""
    text_repr: str
    latex_repr: str | None = None
    source_location: str | None = None
    formula_type: Literal["inline", "display", "image"] = "inline"


class FormulaExtractionError(Exception):
    """Raised when formula extraction fails."""
    pass


def extract_formulas(text: str, context: str = "") -> list[dict]:
    """
    Extract formulas from text and return as list of dicts per spec.

    Returns list of {text_repr, latex_repr, location}.

    Handles: inline LaTeX ($...$), display LaTeX ($$...$$), ASCII formulas.
    """
    formulas = []

    # Display LaTeX: $$...$$
    display_pattern = r"\$\$(.+?)\$\$"
    for match in re.finditer(display_pattern, text, re.DOTALL):
        raw = match.group(1).strip()
        latex = _normalize_latex(raw)
        location = f"pos:{match.start()}-{match.end()}"
        formulas.append({
            "text_repr": raw,
            "latex_repr": latex,
            "location": location,
        })

    # Inline LaTeX: $...$
    inline_pattern = r"(?<!\$)\$(.+?)\$(?!\$)"
    for match in re.finditer(inline_pattern, text):
        raw = match.group(1).strip()
        if re.match(r"^\d+(\.\d+)?$", raw):
            continue
        latex = _normalize_latex(raw)
        location = f"pos:{match.start()}-{match.end()}"
        formulas.append({
            "text_repr": raw,
            "latex_repr": latex,
            "location": location,
        })

    return formulas


def _normalize_latex(raw: str) -> str:
    """Normalize LaTeX formula string."""
    latex = raw.strip()
    latex = latex.replace("\\ ", " ")
    latex = latex.replace("  ", " ")
    return latex


def extract_formulas_from_image(image_bytes: bytes, context: str = "") -> Optional[FormulaInfo]:
    """
    Extract formula from image using OCR.

    Priority:
    1. Qwen/Qwen3.5-9B vision endpoint (primary — self-hosted)
    2. Nougat (local, offline — currently placeholder)
    3. MathPix API (optional fallback — requires MATHPIX_APP_ID + MATHPIX_APP_KEY)
    """
    import asyncio

    def _run(coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        except RuntimeError:
            # Already running loop — use new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()

    # ── 1. Qwen vision (primary) ──────────────────────────────────────────────
    try:
        from app.utils.qwen_vision import get_qwen_vision_client
        qwen = get_qwen_vision_client()
        if qwen._enabled:
            latex = _run(qwen.extract_formula_from_image(image_bytes))
            if latex:
                return FormulaInfo(
                    text_repr=latex,
                    latex_repr=latex,
                    formula_type="image",
                    source_location=context[:100] if context else None,
                )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Qwen formula OCR failed: %s", e)

    # ── 2. Nougat (local, placeholder) ───────────────────────────────────────
    try:
        latex = _extract_with_nougat(image_bytes)
        if latex:
            return FormulaInfo(
                text_repr=latex,
                latex_repr=latex,
                formula_type="image",
                source_location=context[:100] if context else None,
            )
    except Exception:
        pass

    # ── 3. MathPix fallback ───────────────────────────────────────────────────
    try:
        latex = _run(_extract_with_mathpix(image_bytes))
        if latex:
            return FormulaInfo(
                text_repr=latex,
                latex_repr=latex,
                formula_type="image",
                source_location=context[:100] if context else None,
            )
    except Exception:
        pass

    return None


def _extract_with_nougat(image_bytes: bytes) -> str | None:
    """Extract LaTeX from image using Nougat (Meta). Currently placeholder."""
    return None


async def _extract_with_mathpix(image_bytes: bytes) -> str | None:
    """Extract LaTeX from image using MathPix API (optional fallback)."""
    from app.core.config import get_settings
    import httpx

    settings = get_settings()

    if not settings.MATHPIX_APP_ID or not settings.MATHPIX_APP_KEY:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.mathpix.com/v3/pdf",
                headers={
                    "app_id": settings.MATHPIX_APP_ID,
                    "app_key": settings.MATHPIX_APP_KEY,
                },
                files={"file": ("formula.png", image_bytes, "image/png")},
                data={
                    "formats": ["latex"],
                    "math_inline_delimiters": ["$", "$"],
                },
                timeout=10.0,
            )

        if response.status_code == 200:
            data = response.json()
            return data.get("latex", [None])[0]
    except Exception:
        return None

    return None


async def extract_image_description(image_bytes: bytes, context: str = "") -> str:
    """
    Generate a text description of an image.

    Priority:
    1. Qwen/Qwen3.5-9B vision endpoint (primary — self-hosted)
    2. LLMClient.chat_vision() (existing GPT-4o / Groq vision fallback)
    """
    # ── 1. Qwen vision (primary) ──────────────────────────────────────────────
    try:
        from app.utils.qwen_vision import get_qwen_vision_client
        qwen = get_qwen_vision_client()
        if qwen._enabled:
            result = await qwen.describe_image(image_bytes, context=context)
            if result:
                return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Qwen describe_image failed: %s — falling back", e)

    # ── 2. LLMClient vision fallback ─────────────────────────────────────────
    try:
        from app.agents.llm import get_llm_client

        client = get_llm_client()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        response = await client.chat_vision(
            messages=[{"role": "user", "content": """Bạn là assistant mô tả hình ảnh trong sách giáo khoa vật lý tiếng Việt.
Mô tả hình ảnh một cách chính xác, bao gồm:
- Loại hình (đồ thị, sơ đồ, hình minh họa thực nghiệm, ...)
- Các đại lượng vật lý có trong hình
- Mô tả ngắn gọn nội dung cần truyền đạt
Trả về dưới dạng text thuần, không dùng markdown. Nếu không thể mô tả, trả về chuỗi rỗng."""}],
            image_base64=base64_image,
            image_media_type="image/png",
        )

        return response.strip()

    except Exception:
        return ""
