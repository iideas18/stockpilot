"""Multi-LLM provider abstraction layer.

Supports OpenAI, Anthropic, Google Gemini, DeepSeek, xAI (Grok),
Azure OpenAI, OpenRouter, GigaChat, and Ollama.

Updated 2026-04: Added xAI/Grok-4, Azure OpenAI, OpenRouter, GigaChat providers.
New models: GPT-5.4, Claude Sonnet/Opus/Haiku 4.6, Gemini 3 Pro, Qwen 3, GLM-4.5.
"""

from __future__ import annotations

import logging
from typing import Any

from stockpilot.config import get_settings

logger = logging.getLogger(__name__)

# Supported LLM models registry (from ai-hedge-fund upstream)
SUPPORTED_MODELS = [
    {"display_name": "Grok 4", "model_name": "grok-4-0709", "provider": "xai"},
    {"display_name": "GPT-5.4", "model_name": "gpt-5.4", "provider": "openai"},
    {"display_name": "GPT-4.1", "model_name": "gpt-4.1", "provider": "openai"},
    {"display_name": "Claude Sonnet 4.6", "model_name": "claude-sonnet-4-6", "provider": "anthropic"},
    {"display_name": "Claude Haiku 4.6", "model_name": "claude-haiku-4-6", "provider": "anthropic"},
    {"display_name": "Claude Opus 4.6", "model_name": "claude-opus-4-6", "provider": "anthropic"},
    {"display_name": "DeepSeek R1", "model_name": "deepseek-reasoner", "provider": "deepseek"},
    {"display_name": "DeepSeek V3", "model_name": "deepseek-chat", "provider": "deepseek"},
    {"display_name": "Gemini 3 Pro", "model_name": "gemini-3-pro-preview", "provider": "google"},
    {"display_name": "GLM-4.5 Air", "model_name": "z-ai/glm-4.5-air", "provider": "openrouter"},
    {"display_name": "GLM-4.5", "model_name": "z-ai/glm-4.5", "provider": "openrouter"},
    {"display_name": "Qwen 3 (235B) Thinking", "model_name": "qwen/qwen3-235b-a22b-thinking-2507", "provider": "openrouter"},
    {"display_name": "GigaChat-2-Max", "model_name": "GigaChat-2-Max", "provider": "gigachat"},
]


def get_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    **kwargs: Any,
):
    """Get a LangChain LLM instance.

    Args:
        provider: LLM provider (openai, anthropic, google, deepseek, xai,
                  openrouter, gigachat, azure_openai, ollama)
        model: Model name override
        temperature: Temperature override
        max_tokens: Max tokens override

    Returns:
        LangChain BaseChatModel instance
    """
    settings = get_settings()
    provider = provider or settings.llm.default_provider
    model = model or settings.llm.default_model
    temperature = temperature if temperature is not None else settings.llm.temperature
    max_tokens = max_tokens or settings.llm.max_tokens

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        init_kwargs = dict(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=settings.llm.openai_api_key or None,
            **kwargs,
        )
        if settings.llm.openai_base_url:
            init_kwargs["base_url"] = settings.llm.openai_base_url
        return ChatOpenAI(**init_kwargs)
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-sonnet-4-6",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=settings.llm.anthropic_api_key or None,
            **kwargs,
        )
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model or "gemini-3-pro-preview",
            temperature=temperature,
            max_output_tokens=max_tokens,
            google_api_key=settings.llm.google_api_key or None,
            **kwargs,
        )
    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "deepseek-chat",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=settings.llm.deepseek_api_key or None,
            base_url="https://api.deepseek.com/v1",
            **kwargs,
        )
    elif provider == "xai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "grok-4-0709",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=getattr(settings.llm, "xai_api_key", None) or None,
            base_url="https://api.x.ai/v1",
            **kwargs,
        )
    elif provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "z-ai/glm-4.5",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=getattr(settings.llm, "openrouter_api_key", None) or None,
            base_url="https://openrouter.ai/api/v1",
            **kwargs,
        )
    elif provider == "azure_openai":
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=getattr(settings.llm, "azure_api_key", None) or None,
            azure_endpoint=getattr(settings.llm, "azure_endpoint", None) or "",
            api_version=getattr(settings.llm, "azure_api_version", "2024-02-01"),
            **kwargs,
        )
    elif provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=model or "llama3",
            temperature=temperature,
            **kwargs,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. "
                         f"Supported: openai, anthropic, google, deepseek, xai, "
                         f"openrouter, azure_openai, ollama")


def get_analyst_llm(**kwargs):
    """Get LLM configured for analyst agents (cost-optimized)."""
    settings = get_settings()
    return get_llm(model=settings.llm.analyst_model, **kwargs)


def get_debate_llm(**kwargs):
    """Get LLM configured for debate agents (full capability)."""
    settings = get_settings()
    return get_llm(model=settings.llm.debate_model, **kwargs)


def get_supported_models() -> list[dict]:
    """Return list of all supported LLM models."""
    return SUPPORTED_MODELS.copy()
