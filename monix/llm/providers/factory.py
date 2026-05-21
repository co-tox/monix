from __future__ import annotations

from typing import Optional

from monix.llm.client import GeminiClient
from monix.llm.providers.base import LLMClient
from monix.llm.providers.codex import CodexClient, DEFAULT_CODEX_MODEL
from monix.llm.types import AuthError


GEMINI_PROVIDER = "gemini"
CODEX_PROVIDER = "openai-codex"


def create_client(
    *,
    provider: str,
    model: str,
    gemini_api_key: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
) -> LLMClient:
    if provider == CODEX_PROVIDER:
        return CodexClient(
            model=model or DEFAULT_CODEX_MODEL,
            max_output_tokens=max_output_tokens,
            timeout=timeout,
        )
    if provider == GEMINI_PROVIDER:
        return GeminiClient(
            api_key=gemini_api_key,
            model=model,
            max_output_tokens=max_output_tokens,
            timeout=timeout,
        )
    raise AuthError(f"Unsupported LLM provider: {provider}")


def create_client_from_settings(
    settings: object,
    *,
    max_output_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
) -> LLMClient:
    provider = getattr(settings, "llm_provider", None) or GEMINI_PROVIDER
    return create_client(
        provider=provider,
        model=getattr(settings, "model", ""),
        gemini_api_key=getattr(settings, "gemini_api_key", None),
        max_output_tokens=max_output_tokens,
        timeout=timeout,
    )


def provider_label(provider: str) -> str:
    if provider == CODEX_PROVIDER:
        return "OpenAI Codex"
    return "Gemini"
