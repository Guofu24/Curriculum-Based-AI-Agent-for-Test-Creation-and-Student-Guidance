"""
ChatG4F — LangChain-compatible wrapper for GPT4Free (g4f).

Uses g4f's AsyncClient (OpenAI-compatible) so it works with LangGraph's
async ainvoke without blocking the event loop.

Common working providers (set G4F_PROVIDER in .env):
  Blackbox, DDG, Airforce, DeepInfra, Groq
"""
import asyncio
import logging
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage, AIMessage, HumanMessage, SystemMessage
)
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

logger = logging.getLogger(__name__)


def _resolve_provider(provider_str: Optional[str]):
    """Convert provider name string to g4f provider class."""
    if not provider_str:
        return None
    try:
        import g4f.Provider as providers
        return getattr(providers, provider_str, None)
    except Exception:
        return None


def _to_g4f_messages(messages: List[BaseMessage]) -> List[dict]:
    result = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append({"role": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": msg.content})
        else:
            result.append({"role": "user", "content": str(msg.content)})
    return result


class ChatG4F(BaseChatModel):
    """LangChain ChatModel backed by g4f (GPT4Free)."""

    model: str = "gpt-4o"
    temperature: float = 0.7
    provider: Optional[str] = "Blackbox"  # provider name string, e.g. "Blackbox", "DDG"

    @property
    def _llm_type(self) -> str:
        return "g4f"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Sync fallback using g4f ChatCompletion."""
        import g4f
        converted = _to_g4f_messages(messages)
        provider_cls = _resolve_provider(self.provider)
        response = g4f.ChatCompletion.create(
            model=self.model,
            messages=converted,
            provider=provider_cls,
        )
        content = response if isinstance(response, str) else str(response)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async generation using g4f AsyncClient."""
        from g4f.client import AsyncClient
        converted = _to_g4f_messages(messages)
        provider_cls = _resolve_provider(self.provider)

        try:
            client = AsyncClient(provider=provider_cls)
            response = await client.chat.completions.create(
                model=self.model,
                messages=converted,
            )
            content = response.choices[0].message.content or ""
            logger.debug(f"g4f [{self.provider}] response (first 200): {content[:200]}")
        except Exception as e:
            logger.warning(f"g4f AsyncClient failed ({e}), falling back to sync")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: self._generate(messages))
            return result

        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )
