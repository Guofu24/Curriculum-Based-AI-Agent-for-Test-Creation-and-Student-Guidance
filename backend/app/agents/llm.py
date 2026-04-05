"""LLM Provider Abstraction Layer.

Supports: OpenAI, OpenRouter, Groq, g4f, Ollama, Anthropic.
All agents call through the unified interface: LLMClient.
Switch provider via .env — no code changes needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.observability.tracer import CurriculumTracer

logger = logging.getLogger(__name__)
settings = get_settings()
T = TypeVar("T", bound=BaseModel)


# ============================================================
# TRACER WRAPPER (lazy import to avoid circular dependency)
# ============================================================

def _get_tracer() -> "CurriculumTracer | None":
    try:
        from app.observability.tracer import get_tracer
        return get_tracer()
    except Exception:
        return None


# ============================================================
# ABSTRACT BASE PROVIDER
# ============================================================

class BaseLLMProvider(ABC):
    """Interface chung cho tất cả LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> str:
        """Gọi LLM, trả về string response."""
        ...

    @abstractmethod
    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        model: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        **kwargs,
    ) -> T:
        """Gọi LLM, trả về Pydantic model. Auto-retry nếu parse fail."""
        ...

    def supports_vision(self) -> bool:
        """Provider có hỗ trợ image input không."""
        return False

    def name(self) -> str:
        return self.__class__.__name__.replace("Provider", "").lower()


# ============================================================
# OPENAI PROVIDER
# ============================================================

class OpenAIProvider(BaseLLMProvider):
    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs) -> str:  # noqa: ARG002
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        model: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> T:
        import instructor
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        inst = instructor.from_openai(client)
        return await inst.chat.completions.create(
            model=model,
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_retries=max_retries,
        )

    def supports_vision(self) -> bool:
        return True


# ============================================================
# OPENROUTER PROVIDER
# ============================================================

class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter: 1 API key dùng được 200+ models. URL: https://openrouter.ai"""

    BASE_URL = "https://openrouter.ai/api/v1"

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=self.BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/curriculum-ai",
                "X-Title": settings.OPENROUTER_APP_NAME,
            },
        )
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        model: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> T:
        import instructor
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=self.BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/curriculum-ai",
                "X-Title": settings.OPENROUTER_APP_NAME,
            },
        )
        inst = instructor.from_openai(client)
        return await inst.chat.completions.create(
            model=model,
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_retries=max_retries,
        )

    def supports_vision(self) -> bool:
        return True


# ============================================================
# GROQ PROVIDER
# ============================================================

class GroqProvider(BaseLLMProvider):
    """Groq: Inference cực nhanh (LPU chip), free tier 14,400 req/ngày. URL: https://console.groq.com"""

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        from groq import AsyncGroq

        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        model: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> T:
        import instructor
        from groq import AsyncGroq

        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        inst = instructor.from_groq(client, mode=instructor.Mode.JSON)
        return await inst.chat.completions.create(
            model=model,
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_retries=max_retries,
        )

    def supports_vision(self) -> bool:
        return True


# ============================================================
# ANTHROPIC PROVIDER
# ============================================================

class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude. Models: claude-3-5-sonnet, claude-3-haiku."""

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

        # Anthropic tách system message riêng
        system = ""
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                filtered.append(m)

        resp = await client.messages.create(
            model=model,
            messages=filtered,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.content[0].text

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        model: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> T:
        import anthropic
        import instructor

        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

        system = ""
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                filtered.append(m)

        inst = instructor.from_anthropic(client)
        return await inst.messages.create(
            model=model,
            messages=filtered,
            system=system,
            response_model=response_model,
            max_tokens=4096,
            temperature=temperature,
            max_retries=max_retries,
        )

    def supports_vision(self) -> bool:
        return True


# ============================================================
# OLLAMA PROVIDER (local, offline)
# ============================================================

class OllamaProvider(BaseLLMProvider):
    """Ollama: chạy LLM hoàn toàn local. Cài: https://ollama.ai"""

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=f"{settings.OLLAMA_BASE_URL}/v1",
            api_key="ollama",
        )
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        model: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> T:
        import instructor
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=f"{settings.OLLAMA_BASE_URL}/v1",
            api_key="ollama",
        )
        inst = instructor.from_openai(client, mode=instructor.Mode.JSON)

        try:
            return await inst.chat.completions.create(
                model=model,
                messages=messages,
                response_model=response_model,
                temperature=temperature,
                max_retries=max_retries,
            )
        except Exception:
            # Manual JSON extraction fallback
            schema = response_model.model_json_schema()
            augmented_messages = messages + [{
                "role": "user",
                "content": f"Respond with ONLY valid JSON matching this schema (no markdown, no explanation): {json.dumps(schema, ensure_ascii=False)}",
            }]
            raw = await self.chat(augmented_messages, model, temperature=0)
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                return response_model.model_validate_json(json_match.group())
            raise ValueError(f"Cannot parse JSON from Ollama response: {raw[:200]}")

    def supports_vision(self) -> bool:
        return False


# ============================================================
# G4F PROVIDER (không cần API key — dev/test only)
# ============================================================

class G4FProvider(BaseLLMProvider):
    """g4f (gpt4free): reverse engineering, không cần API key. Chỉ dev/test."""

    def __init__(self) -> None:
        import g4f
        self._g4f = g4f

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        import g4f

        # g4f has its own model pool — don't pass Groq/OpenAI model names.
        # Use g4f's auto-selection (picks best available).
        g4f_model = getattr(g4f.models, "gpt_4o_mini", None) or getattr(g4f.models, "gpt_4o", None)
        if g4f_model is None:
            # Last-resort fallback
            g4f_model = "gpt-4o-mini"

        response = await g4f.ChatCompletion.create_async(
            model=g4f_model,
            messages=messages,
        )
        return str(response)

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        model: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> T:
        schema = response_model.model_json_schema()
        json_instruction = {
            "role": "system",
            "content": (
                "You must respond with ONLY valid JSON, no markdown, no explanation. "
                f"JSON schema to follow: {json.dumps(schema, ensure_ascii=False)}"
            ),
        }
        augmented = [json_instruction] + [m for m in messages if m.get("role") != "system"]

        for attempt in range(max_retries):
            try:
                raw = await self.chat(augmented, model, temperature=0)
                raw = raw.strip()
                if raw.startswith("```"):
                    parts = raw.split("```")
                    if len(parts) >= 3:
                        raw = parts[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                return response_model.model_validate_json(raw.strip())
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"G4F structured attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1)

    def supports_vision(self) -> bool:
        return False


# ============================================================
# QWEN VISION PROVIDER (self-hosted VLM via ngrok)
# ============================================================

class QwenVisionProvider(BaseLLMProvider):
    """
    Self-hosted Qwen3.5-9B via ngrok tunnel.
    Uses QWEN_VISION_BASE_URL from .env (e.g. https://xxxx.ngrok-free.app).
    OpenAI-compatible /v1/chat/completions endpoint.
    """

    def __init__(self) -> None:
        base = settings.QWEN_VISION_BASE_URL.rstrip("/")
        if not base:
            raise RuntimeError("QWEN_VISION_BASE_URL is not set in .env")
        self._base_url = f"{base}/v1"

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key="not-needed", base_url=self._base_url)
        resp = await client.chat.completions.create(
            model=model or "Qwen/Qwen3.5-9B",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        model: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> T:
        import instructor
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key="not-needed", base_url=self._base_url)
        inst = instructor.from_openai(client)
        return await inst.chat.completions.create(
            model=model or "Qwen/Qwen3.5-9B",
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_retries=max_retries,
        )

    def supports_vision(self) -> bool:
        return True


# ============================================================
# PROVIDER FACTORY
# ============================================================

_PROVIDER_MAP: dict[str, type[BaseLLMProvider]] = {
    "openai": OpenAIProvider,
    "openrouter": OpenRouterProvider,
    "groq": GroqProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
    "g4f": G4FProvider,
    "qwen_vision": QwenVisionProvider,
}


def _is_provider_available(name: str) -> bool:
    """Return True if a provider has a valid (non-empty) API key configured."""
    s = settings
    if name == "openai":
        return bool(s.OPENAI_API_KEY)
    if name == "openrouter":
        return bool(s.OPENROUTER_API_KEY)
    if name == "groq":
        return bool(s.GROQ_API_KEY)
    if name == "anthropic":
        return bool(s.ANTHROPIC_API_KEY)
    if name == "ollama":
        return True  # local server, no key needed
    if name == "g4f":
        return True  # free aggregator, no key needed
    if name == "qwen_vision":
        return bool(s.QWEN_VISION_BASE_URL)
    return False


def _build_provider(name: str) -> BaseLLMProvider:
    cls = _PROVIDER_MAP.get(name.lower())
    if not cls:
        raise ValueError(
            f"Unknown LLM provider: '{name}'. Available: {list(_PROVIDER_MAP.keys())}"
        )
    try:
        return cls()
    except Exception as e:
        raise RuntimeError(f"Failed to init provider '{name}': {e}") from e


# ============================================================
# MAIN LLM CLIENT — Entry point cho tất cả agents
# ============================================================

class LLMClient:
    """
    Unified LLM client với:
    - Provider abstraction (swap qua .env)
    - Role-based model routing
    - Automatic fallback chain
    - LangFuse tracing
    """

    # Role → model tier mapping
    STRONG_ROLES: set[str] = {"orchestrator", "builder", "validator"}
    LIGHT_ROLES: set[str] = {"planner", "reranker", "outline", "dedup", "skills", "classifier"}

    def __init__(self) -> None:
        primary_name = settings.LLM_PROVIDER
        if not _is_provider_available(primary_name):
            logger.warning(
                f"Primary provider '{primary_name}' has no API key — "
                f"falling back to available providers."
            )

        self._primary: BaseLLMProvider | None = None
        self._fallbacks: list[BaseLLMProvider] = []

        # Try primary first if available
        if _is_provider_available(primary_name):
            try:
                self._primary = _build_provider(primary_name)
            except Exception as e:
                logger.warning(f"Primary provider '{primary_name}' init failed: {e}")

        # Build fallback chain, skipping unavailable ones
        for name in settings.fallback_providers:
            if name == primary_name:
                continue
            if not _is_provider_available(name):
                continue
            try:
                self._fallbacks.append(_build_provider(name))
            except Exception as e:
                logger.warning(f"Fallback provider '{name}' init failed: {e}")

        if not self._primary and not self._fallbacks:
            raise RuntimeError(
                "No LLM provider available. Set at least one of: "
                "GROQ_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, "
                "ANTHROPIC_API_KEY (or ensure Ollama/G4F is reachable)."
            )

        logger.info(
            f"LLMClient ready | primary={self._primary.name() if self._primary else 'NONE'} "
            f"| fallbacks={[p.name() for p in self._fallbacks]}"
        )

    def _get_model(self, role: str) -> str:
        """Chọn model dựa trên role."""
        if role in self.STRONG_ROLES:
            return settings.LLM_MODEL_STRONG
        if role == "vision":
            return settings.LLM_MODEL_VISION
        return settings.LLM_MODEL_LIGHT

    async def chat(
        self,
        messages: list[dict],
        role: str = "default",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        trace_name: str | None = None,
    ) -> str:
        """
        Gọi LLM, trả về string.
        role: "orchestrator" | "builder" | "validator" | "planner" | "outline" | ...
        model: override model name nếu cần (thường để None)
        trace_name: tên span cho LangFuse tracing
        """
        resolved_model = model or self._get_model(role)
        primary_provider = self._primary
        providers = ([primary_provider] if primary_provider else []) + self._fallbacks

        tracer = _get_tracer()
        last_error: Exception | None = None
        span: Any = None

        for provider in providers:
            try:
                start = time.time()

                if tracer is not None:
                    try:
                        span = tracer._lf.span(
                            name=f"llm:{trace_name or role}",
                            metadata={
                                "provider": provider.name(),
                                "model": resolved_model,
                                "role": role,
                            },
                        )
                    except Exception:
                        pass

                result = await provider.chat(
                    messages=messages,
                    model=resolved_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if span is not None:
                    try:
                        span.end(metadata={"latency_ms": int((time.time() - start) * 1000)})
                    except Exception:
                        pass

                logger.debug(
                    f"LLM chat ok | provider={provider.name()} "
                    f"| model={resolved_model} | latency={int((time.time() - start) * 1000)}ms"
                )
                return result
            except Exception as e:
                last_error = e
                if span is not None:
                    try:
                        span.end(metadata={"error": str(e)})
                    except Exception:
                        pass
                span = None
                logger.warning(
                    f"Provider {provider.name()} failed: {e}. Trying next fallback..."
                )
                continue

        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_error}"
        )

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        role: str = "default",
        model: str | None = None,
        temperature: float = 0.3,
        max_retries: int = 3,
        trace_name: str | None = None,
    ) -> T:
        """
        Gọi LLM, trả về Pydantic model.
        Auto-retry nếu parse fail. Fallback qua providers nếu cần.
        """
        resolved_model = model or self._get_model(role)
        primary_provider = self._primary
        providers = ([primary_provider] if primary_provider else []) + self._fallbacks

        tracer = _get_tracer()
        last_error: Exception | None = None

        for provider in providers:
            try:
                span: Any = None
                if tracer is not None:
                    try:
                        span = tracer._lf.span(
                            name=f"llm_structured:{trace_name or role}",
                            metadata={
                                "provider": provider.name(),
                                "model": resolved_model,
                                "response_model": response_model.__name__,
                            },
                        )
                    except Exception:
                        pass

                result = await provider.chat_structured(
                    messages=messages,
                    response_model=response_model,
                    model=resolved_model,
                    temperature=temperature,
                    max_retries=max_retries,
                )

                if span is not None:
                    try:
                        span.end()
                    except Exception:
                        pass

                return result
            except Exception as e:
                last_error = e
                if span is not None:
                    try:
                        span.end(metadata={"error": str(e)})
                    except Exception:
                        pass
                logger.warning(
                    f"Provider {provider.name()} structured failed: {e}. Trying next..."
                )
                continue

        raise RuntimeError(
            f"All providers failed for structured output. Last error: {last_error}"
        )

    async def rerank(
        self,
        query: str,
        candidates: list[str],
        top_k: int = 8,
        role: str = "reranker",
    ) -> list[tuple[int, float]]:
        """
        Rerank candidates using LLM scoring.
        Returns list of (candidate_index, relevance_score) sorted by score.
        """
        prompt = f"""Bạn là chuyên gia đánh giá độ liên quan giữa câu hỏi và các đoạn văn bản.
Câu hỏi: {query}

Đánh giá từng đoạn văn bản và gán điểm liên quan từ 0.0 đến 1.0.
Trả về JSON array với format:
[
  {{"index": 0, "score": 0.95}},
  {{"index": 1, "score": 0.72}},
  ...
]

Các đoạn văn bản:
{json.dumps([{"index": i, "text": c[:500]} for i, c in enumerate(candidates)], ensure_ascii=False, indent=2)}"""

        try:
            response = await self.chat(
                messages=[{"role": "user", "content": prompt}],
                role=role,
                max_tokens=2000,
                temperature=0.1,
            )
            data = json.loads(response)
            results = [(item["index"], item["score"]) for item in data]
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]
        except Exception:
            return [(i, 1.0 / (i + 1)) for i in range(min(len(candidates), top_k))]

    async def chat_vision(
        self,
        messages: list[dict],
        image_base64: str,
        image_media_type: str = "image/jpeg",
    ) -> str:
        """
        Gọi LLM với image input (cho RAG image description).
        Tự chọn provider hỗ trợ vision.
        """
        vision_providers = [
            p for p in [self._primary] + self._fallbacks
            if p.supports_vision()
        ]
        if not vision_providers:
            logger.warning("No vision-capable provider available.")
            return "Hình ảnh không thể mô tả (không có vision provider)."

        # Inject image vào messages theo format OpenAI vision
        vision_messages = []
        for m in messages:
            if m["role"] == "user":
                vision_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": m["content"]},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_media_type};base64,{image_base64}"
                            },
                        },
                    ],
                })
            else:
                vision_messages.append(m)

        model = settings.LLM_MODEL_VISION
        for provider in vision_providers:
            try:
                return await provider.chat(vision_messages, model=model)
            except Exception as e:
                logger.warning(f"Vision provider {provider.name()} failed: {e}")
                continue

        return "Không thể mô tả hình ảnh."


# ============================================================
# SINGLETON
# ============================================================

_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get the singleton LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def reset_llm_client() -> None:
    """Reset the singleton (useful for testing or config reload)."""
    global _llm_client
    _llm_client = None
