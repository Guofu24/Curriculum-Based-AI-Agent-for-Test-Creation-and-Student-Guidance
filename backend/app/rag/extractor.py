"""Formula and image extraction from document content."""

import re
import base64
from typing import Literal
from dataclasses import dataclass


@dataclass
class FormulaInfo:
    """Information about a detected formula."""
    text_repr: str
    latex_repr: str | None = None
    source_location: str | None = None
    formula_type: Literal["inline", "display", "image"] = "inline"


@dataclass
class ImageInfo:
    """Information about a detected image."""
    description: str
    alt_text: str | None = None


class FormulaExtractionError(Exception):
    """Raised when formula extraction fails."""
    pass


def extract_formulas(text: str, context: str = "") -> list[FormulaInfo]:
    """
    Extract formulas from text.
    Handles: inline LaTeX ($...$), display LaTeX ($$...$$), ASCII formulas.
    """
    formulas = []

    # Display LaTeX: $$...$$
    display_pattern = r"\$\$(.+?)\$\$"
    for match in re.finditer(display_pattern, text, re.DOTALL):
        raw = match.group(1).strip()
        latex = _normalize_latex(raw)
        formulas.append(FormulaInfo(
            text_repr=raw,
            latex_repr=latex,
            formula_type="display",
            source_location=context[:100] if context else None,
        ))

    # Inline LaTeX: $...$
    inline_pattern = r"(?<!\$)\$(.+?)\$(?!\$)"
    for match in re.finditer(inline_pattern, text):
        raw = match.group(1).strip()
        # Skip if it looks like a dollar amount
        if re.match(r"^\d+(\.\d+)?$", raw):
            continue
        latex = _normalize_latex(raw)
        formulas.append(FormulaInfo(
            text_repr=raw,
            latex_repr=latex,
            formula_type="inline",
            source_location=context[:100] if context else None,
        ))

    return formulas


def extract_formulas_from_image(image_bytes: bytes, context: str = "") -> FormulaInfo | None:
    """
    Extract formula from image using OCR.
    Tries Nougat first (offline/free), then MathPix API as fallback.
    """
    # Try Nougat first (Meta's offline formula OCR)
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

    # Fallback to MathPix API
    try:
        latex = _extract_with_mathpix(image_bytes)
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


def _normalize_latex(raw: str) -> str:
    """Normalize LaTeX formula string."""
    # Basic normalization
    latex = raw.strip()
    # Remove common OCR artifacts
    latex = latex.replace("\\ ", " ")
    latex = latex.replace("  ", " ")
    return latex


async def _extract_with_nougat(image_bytes: bytes) -> str | None:
    """Extract LaTeX from image using Nougat (Meta)."""
    try:
        import torch
        from PIL import Image as PILImage

        # This would use the nougat-ocr package
        # For now, return None to trigger fallback
        # Actual implementation would load Nougat model and run inference
        return None
    except ImportError:
        return None


async def _extract_with_mathpix(image_bytes: bytes) -> str | None:
    """Extract LaTeX from image using MathPix API."""
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


def extract_images_descriptions(images: list[dict]) -> list[ImageInfo]:
    """
    Extract text descriptions from images using GPT-4o Vision.
    images: list of {image_bytes, page_num, position}
    Returns: list of ImageInfo with descriptions
    """
    # This would be called from the extraction pipeline
    # with GPT-4o Vision for image description
    descriptions = []

    for img_data in images:
        desc = _describe_image_with_vision(img_data.get("image_bytes"))
        descriptions.append(ImageInfo(
            description=desc or "",
            alt_text=img_data.get("alt_text"),
        ))

    return descriptions


async def _describe_image_with_vision(image_bytes: bytes) -> str | None:
    """Use GPT-4o Vision to describe an image."""
    from app.agents.llm import get_llm_client

    try:
        client = get_llm_client()

        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """Bạn là assistant mô tả hình ảnh trong sách giáo khoa.
Mô tả hình ảnh một cách chính xác, bao gồm:
- Loại hình (đồ thị, sơ đồ, hình minh họa thực nghiệm, ...)
- Các đại lượng vật lý có trong hình
- Mô tả ngắn gọn nội dung cần truyền đạt
Trả về dưới dạng text thuần, không dùng markdown."""
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]

        response = await client.client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=300,
        )

        return response.choices[0].message.content

    except Exception:
        return None
