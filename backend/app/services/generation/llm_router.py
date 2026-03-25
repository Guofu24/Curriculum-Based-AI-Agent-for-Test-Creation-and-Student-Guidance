"""
LLM provider factory for the active generation runtime

Centralizes all provider instantiation logic that was previously
scattered in ExamService._get_llm().  Returns an instrumented
LLMBackend wrapper so every call is automatically logged.

Usage:
    from app.services.generation.llm_router import create_llm
    llm = create_llm()                # uses settings.LLM_PROVIDER
    llm = create_llm("google")        # explicit override
    llm = create_llm(fallback="g4f")  # try primary, fallback on import error
"""
import logging
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import settings
from app.services.generation.llm_backend import LLMBackend

logger = logging.getLogger(__name__)


def create_llm(
    provider: Optional[str] = None,
    fallback: Optional[str] = None,
    temperature: float = 0.7,
) -> LLMBackend:
    """
    Create an instrumented LLM instance for the given provider.

    Args:
        provider:    Provider name override (default: settings.LLM_PROVIDER)
        fallback:    Fallback provider if primary fails to initialize
        temperature: Sampling temperature

    Returns:
        LLMBackend wrapping the concrete BaseChatModel
    """
    provider = provider or settings.LLM_PROVIDER

    try:
        inner, model_name = _build_provider(provider, temperature)
    except Exception as e:
        if fallback and fallback != provider:
            logger.warning(
                f"Primary provider '{provider}' failed ({e}), "
                f"falling back to '{fallback}'"
            )
            inner, model_name = _build_provider(fallback, temperature)
            provider = fallback
        else:
            raise

    backend = LLMBackend(
        inner=inner,
        provider_name=provider,
        model_name=model_name,
    )
    logger.info(f"LLM router: provider={provider}, model={model_name}")
    return backend


# â”€â”€ Provider builders (one per supported provider) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_provider(
    provider: str,
    temperature: float,
) -> tuple[BaseChatModel, str]:
    """
    Instantiate a raw LangChain BaseChatModel for the given provider.

    Returns (model_instance, model_name_str).
    """
    builder = _PROVIDERS.get(provider)
    if builder is None:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. "
            f"Available: {list(_PROVIDERS.keys())}"
        )
    return builder(temperature)


def _build_groq(temperature: float) -> tuple[BaseChatModel, str]:
    from langchain_groq import ChatGroq
    return (
        ChatGroq(
            model=settings.GROQ_MODEL,
            api_key=settings.GROQ_API_KEY,
            temperature=temperature,
        ),
        settings.GROQ_MODEL,
    )


def _build_g4f(temperature: float) -> tuple[BaseChatModel, str]:
    from app.services.generation.llm_g4f import ChatG4F
    return (
        ChatG4F(
            model=settings.G4F_MODEL,
            provider=settings.G4F_PROVIDER or None,
            temperature=temperature,
        ),
        f"g4f/{settings.G4F_MODEL}",
    )


def _build_together(temperature: float) -> tuple[BaseChatModel, str]:
    from langchain_openai import ChatOpenAI
    return (
        ChatOpenAI(
            model=settings.TOGETHER_MODEL,
            api_key=settings.TOGETHER_API_KEY,
            base_url="https://api.together.xyz/v1",
            temperature=temperature,
        ),
        settings.TOGETHER_MODEL,
    )


def _build_google(temperature: float) -> tuple[BaseChatModel, str]:
    from langchain_google_genai import ChatGoogleGenerativeAI
    return (
        ChatGoogleGenerativeAI(
            model=settings.GOOGLE_MODEL,
            google_api_key=settings.GOOGLE_API_KEY,
            temperature=temperature,
        ),
        settings.GOOGLE_MODEL,
    )


def _build_openai(temperature: float) -> tuple[BaseChatModel, str]:
    from langchain_openai import ChatOpenAI
    return (
        ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=temperature,
        ),
        settings.OPENAI_MODEL,
    )


def _build_anthropic(temperature: float) -> tuple[BaseChatModel, str]:
    from langchain_anthropic import ChatAnthropic
    return (
        ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
        ),
        settings.ANTHROPIC_MODEL,
    )


# â”€â”€ Registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_PROVIDERS: dict[str, callable] = {
    "groq": _build_groq,
    "g4f": _build_g4f,
    "together": _build_together,
    "google": _build_google,
    "openai": _build_openai,
    "anthropic": _build_anthropic,
}

