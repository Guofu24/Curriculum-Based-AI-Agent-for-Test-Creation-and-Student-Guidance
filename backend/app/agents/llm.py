"""Shared async OpenAI LLM client with instructor support."""

import asyncio
import time
import json
from typing import Any, Literal, Optional
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.config import get_settings
from app.rag.embedder import calculate_cost

settings = get_settings()

# Token pricing for cost tracking
TOKEN_PRICING = {
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4": {"input": 30.0, "output": 60.0},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-opus": {"input": 15.0, "output": 75.0},
}


class LLMClient:
    """Shared async OpenAI LLM client with model routing."""

    def __init__(self):
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        """Lazy-load OpenAI client."""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
            )
        return self._client

    async def chat(
        self,
        messages: list[dict],
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
        timeout: float = 60.0,
    ) -> dict:
        """
        Make a chat completion call with token tracking.

        Returns:
            {
                "content": str,
                "usage": {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int},
                "cost_usd": float,
                "model": str,
            }
        """
        start_time = time.time()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = await self.client.chat.completions.create(**kwargs)

        elapsed_ms = int((time.time() - start_time) * 1000)
        usage = response.usage

        pricing = TOKEN_PRICING.get(model, {"input": 1.0, "output": 2.0})
        cost = (
            (usage.prompt_tokens / 1_000_000) * pricing["input"]
            + (usage.completion_tokens / 1_000_000) * pricing["output"]
        )

        return {
            "content": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            },
            "cost_usd": round(cost, 6),
            "model": model,
            "latency_ms": elapsed_ms,
        }

    async def chat_with_instructor(
        self,
        messages: list[dict],
        response_model: type[BaseModel],
        model: str = "gpt-4o",
        max_retries: int = 3,
        temperature: float = 0.3,
    ) -> BaseModel:
        """
        Make a structured chat call using instructor for Pydantic output.
        Auto-retries if output doesn't match schema.
        """
        import instructor

        instructor_client = instructor.from_openai(self.client)

        for attempt in range(max_retries):
            try:
                response = await instructor_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_retries=max_retries,
                )
                return response
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                # Brief wait before retry
                await asyncio.sleep(0.5 * (attempt + 1))

        raise Exception(f"Failed after {max_retries} attempts")

    async def rerank(
        self,
        query: str,
        candidates: list[str],
        top_k: int = 8,
        model: str = "gpt-4o-mini",
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

        response = await self.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            response_format={"type": "json_object"},
            max_tokens=2000,
            temperature=0.1,
        )

        try:
            data = json.loads(response["content"])
            results = [(item["index"], item["score"]) for item in data]
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]
        except Exception:
            # Fallback: return uniform scores
            return [(i, 1.0 / (i + 1)) for i in range(min(len(candidates), top_k))]

    def calculate_token_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int = 0,
    ) -> float:
        """Calculate cost for token usage."""
        pricing = TOKEN_PRICING.get(model, {"input": 1.0, "output": 2.0})
        return (
            (prompt_tokens / 1_000_000) * pricing["input"]
            + (completion_tokens / 1_000_000) * pricing["output"]
        )


# Singleton instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get the singleton LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
