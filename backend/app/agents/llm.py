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

# Domain 9: Prompt version mapping by role
_PROMPT_VERSIONS: dict[str, str] = {
    "outline": "v2.1",
    "builder": "v2.1",
    "validator": "v2.1",
    "orchestrator": "v1.0",
    "planner": "v1.0",
    "retrieval": "v1.0",
    "dedup": "v1.0",
    "skills": "v1.0",
    "classifier": "v1.0",
    "guardrails": "v1.0",
    "reranker": "v1.0",
}


def _get_prompt_version(role: str) -> str:
    """Get the prompt version for a given role."""
    return _PROMPT_VERSIONS.get(role, "v1.0")


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
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._base_url = settings.BASE_URL

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs) -> str:  # noqa: ARG002
        from openai import AsyncOpenAI

        async with AsyncOpenAI(api_key=self._api_key, base_url=self._base_url) as client:
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

        async with AsyncOpenAI(api_key=self._api_key, base_url=self._base_url) as client:
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

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.OPENROUTER_API_KEY
        self._app_name = settings.OPENROUTER_APP_NAME

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        from openai import AsyncOpenAI

        async with AsyncOpenAI(
            api_key=self._api_key,
            base_url=self.BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/curriculum-ai",
                "X-Title": self._app_name,
            },
        ) as client:
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

        async with AsyncOpenAI(
            api_key=self._api_key,
            base_url=self.BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/curriculum-ai",
                "X-Title": self._app_name,
            },
        ) as client:
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

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.GROQ_API_KEY

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        from groq import AsyncGroq

        async with AsyncGroq(api_key=self._api_key) as client:
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

        async with AsyncGroq(api_key=self._api_key) as client:
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

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.ANTHROPIC_API_KEY

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        import anthropic

        async with anthropic.AsyncAnthropic(api_key=self._api_key) as client:
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

        async with anthropic.AsyncAnthropic(api_key=self._api_key) as client:
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

    def __init__(self, api_key: str | None = None) -> None:  # noqa: ARG002
        self._base_url = settings.OLLAMA_BASE_URL

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        from openai import AsyncOpenAI

        async with AsyncOpenAI(
            base_url=f"{self._base_url}/v1",
            api_key="ollama",
        ) as client:
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

        async with AsyncOpenAI(
            base_url=f"{self._base_url}/v1",
            api_key="ollama",
        ) as client:
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

    def __init__(self, api_key: str | None = None) -> None:  # noqa: ARG002
        import g4f
        self._g4f = g4f

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        import g4f

        g4f_model = getattr(g4f.models, "gpt_4o_mini", None) or getattr(g4f.models, "gpt_4o", None)
        if g4f_model is None:
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
    Uses VISION_PROVIDER / VISION_API_KEY from .env (e.g. https://xxxx.ngrok-free.app).
    OpenAI-compatible /v1/chat/completions endpoint.
    """

    def __init__(self, base_url: str | None = None) -> None:
        base = base_url or settings.QWEN_VISION_BASE_URL
        if not base:
            raise RuntimeError("QWEN_VISION_BASE_URL is not set in .env")
        self._base_url = f"{base.rstrip('/')}/v1"

    async def chat(self, messages: list[dict], model: str, temperature: float = 0.7, max_tokens: int = 4096, **kwargs: Any) -> str:  # noqa: ARG002
        from openai import AsyncOpenAI

        async with AsyncOpenAI(api_key="not-needed", base_url=self._base_url) as client:
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

        async with AsyncOpenAI(api_key="not-needed", base_url=self._base_url) as client:
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


def _build_provider(name: str, api_key: str | None = None) -> BaseLLMProvider:
    cls = _PROVIDER_MAP.get(name.lower())
    if not cls:
        raise ValueError(
            f"Unknown LLM provider: '{name}'. Available: {list(_PROVIDER_MAP.keys())}"
        )
    try:
        return cls(api_key=api_key)
    except TypeError:
        # Provider không nhận api_key (Ollama, G4F)
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
    LIGHT_ROLES: set[str] = {"planner", "reranker", "outline", "dedup", "skills", "classifier", "guardrails"}

    # Role → config field suffixes
    ROLE_FIELDS: dict[str, str] = {
        "orchestrator": "ORCHESTRATOR",
        "builder": "BUILDER",
        "validator": "VALIDATOR",
        "planner": "PLANNER",
        "reranker": "RERANKER",
        "outline": "OUTLINE",
        "dedup": "DEDUP",
        "skills": "SKILLS",
        "classifier": "CLASSIFIER",
        "guardrails": "GUARDRAILS",
        "vision": "VISION",
    }

    def __init__(self) -> None:
        self._role_providers: dict[str, list[BaseLLMProvider]] = {}
        self._all_providers: dict[str, BaseLLMProvider] = {}
        logger.info("LLMClient ready | per-role provider+apikey+model routing enabled")

    def _get_model(self, role: str) -> str:
        """Chọn model dựa trên role. Ưu tiên: per-role override > tier default."""
        suffix = self.ROLE_FIELDS.get(role)
        if suffix:
            model = getattr(settings, f"{suffix}_MODEL", None)
            if model:
                return model

        if role in self.STRONG_ROLES:
            return settings.LLM_MODEL_STRONG_DEFAULT
        if role == "vision":
            return settings.VISION_MODEL
        return settings.LLM_MODEL_LIGHT_DEFAULT

    def _get_providers_for_role(self, role: str) -> list[BaseLLMProvider]:
        """Lấy danh sách provider cho role, mỗi provider dùng API key riêng của role."""
        if role in self._role_providers:
            return self._role_providers[role]

        suffix = self.ROLE_FIELDS.get(role, "")
        provider_name = getattr(settings, f"{suffix}_PROVIDER", None) or settings.LLM_PROVIDER_DEFAULT
        api_key = getattr(settings, f"{suffix}_API_KEY", None) or ""

        # Build provider instances với key riêng
        role_providers: list[BaseLLMProvider] = []

        # Primary
        key = f"{provider_name}:{api_key}"
        if key not in self._all_providers:
            try:
                self._all_providers[key] = _build_provider(provider_name, api_key=api_key or None)
            except Exception as e:
                logger.warning(f"Provider '{provider_name}' init failed: {e}")
        if key in self._all_providers:
            role_providers.append(self._all_providers[key])

        if not role_providers:
            raise RuntimeError(
                f"No provider available for role '{role}'. "
                f"Check {suffix}_PROVIDER and {suffix}_API_KEY in .env."
            )

        self._role_providers[role] = role_providers
        return role_providers

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
        providers = self._get_providers_for_role(role)

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

                latency_ms = int((time.time() - start) * 1000)

                if span is not None:
                    try:
                        span.end(metadata={"latency_ms": latency_ms})
                    except Exception:
                        pass

                # Domain 9: Structured logging for LLM calls
                logger.debug(
                    "llm_call",
                    extra={
                        "provider": provider.name(),
                        "model": resolved_model,
                        "role": role,
                        "latency_ms": latency_ms,
                        "prompt_version": _get_prompt_version(role),
                    },
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
        providers = self._get_providers_for_role(role)

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
        Dùng provider từ per-role override hoặc fallback chain.
        """
        vision_providers = [
            p for p in self._all_providers.values()
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

        model = settings.VISION_MODEL
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
