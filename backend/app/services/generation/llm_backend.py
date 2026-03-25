"""
LLM backend wrapper for the active generation runtime

Wraps any BaseChatModel (Groq, G4F, OpenAI, Google, Anthropic, Together)
with:
  - Per-call latency measurement
  - Retry counting
  - Error classification
  - Structured ProviderLog records

The wrapper is itself a BaseChatModel so it's a drop-in replacement
everywhere the pipeline uses `llm.ainvoke(messages)`.

Usage:
    from app.services.generation.llm_backend import LLMBackend
    raw_llm = ChatGroq(...)
    llm = LLMBackend(inner=raw_llm, provider_name="groq")
    result = await llm.ainvoke(messages)
    print(llm.logs)  # list[ProviderLog]
"""
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field as PydanticField

logger = logging.getLogger(__name__)


# â”€â”€ Structured log record â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class ProviderLog:
    """Structured log for a single LLM call."""
    provider: str
    model: str = ""
    latency_ms: float = 0.0
    retry_count: int = 0
    success: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    input_chars: int = 0
    output_chars: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# â”€â”€ Instrumented wrapper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class LLMBackend(BaseChatModel):
    """
    Transparent instrumented wrapper around any LangChain BaseChatModel.

    Drop-in compatible: passes all `_generate` / `_agenerate` calls
    through to the inner model while recording ProviderLog entries.

    Attributes:
        inner:          The actual BaseChatModel (ChatGroq, ChatG4F, etc.)
        provider_name:  Human-readable provider label for logs
        model_name:     Model identifier for logs
        logs:           Accumulated ProviderLog records (append-only)
    """

    inner: Any = PydanticField(default=None, exclude=True)
    provider_name: str = "unknown"
    model_name: str = ""
    # Pydantic v2 â€” mutable default via default_factory
    logs: list = PydanticField(default_factory=list, exclude=True)

    @property
    def _llm_type(self) -> str:
        return f"backend:{self.provider_name}"

    # â”€â”€ Sync path â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        log = ProviderLog(
            provider=self.provider_name,
            model=self.model_name,
            input_chars=sum(len(m.content) for m in messages),
        )

        start = time.perf_counter()
        try:
            result = self.inner._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            log.success = True
            if result.generations:
                log.output_chars = len(result.generations[0].message.content)
        except Exception as e:
            log.error_type = type(e).__name__
            log.error_message = str(e)[:200]
            raise
        finally:
            log.latency_ms = round((time.perf_counter() - start) * 1000, 1)
            self.logs.append(log)
            self._emit_log(log)

        return result

    # â”€â”€ Async path â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        log = ProviderLog(
            provider=self.provider_name,
            model=self.model_name,
            input_chars=sum(len(m.content) for m in messages),
        )

        start = time.perf_counter()
        try:
            result = await self.inner._agenerate(
                messages, stop=stop, run_manager=run_manager, **kwargs,
            )
            log.success = True
            if result.generations:
                log.output_chars = len(result.generations[0].message.content)
        except Exception as e:
            log.error_type = type(e).__name__
            log.error_message = str(e)[:200]
            raise
        finally:
            log.latency_ms = round((time.perf_counter() - start) * 1000, 1)
            self.logs.append(log)
            self._emit_log(log)

        return result

    # â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _emit_log(self, log: ProviderLog) -> None:
        """Emit structured log to Python logger."""
        if log.success:
            logger.info(
                f"LLM [{log.provider}/{log.model}] "
                f"{log.latency_ms:.0f}ms "
                f"in={log.input_chars}c out={log.output_chars}c"
            )
        else:
            logger.warning(
                f"LLM [{log.provider}/{log.model}] FAILED "
                f"{log.latency_ms:.0f}ms "
                f"error={log.error_type}: {log.error_message}"
            )

    def drain_logs(self) -> list[dict]:
        """Return and clear all accumulated logs as dicts."""
        result = [log.to_dict() for log in self.logs]
        self.logs.clear()
        return result

