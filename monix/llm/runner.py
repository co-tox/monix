from __future__ import annotations

import os
from typing import Any, Optional

from monix.llm import executor, registry, trimmer
from monix.llm.client import GeminiClient, MODEL_FLASH, MODEL_PRO
from monix.llm.types import History, LLMError


_DEFAULT_MAX_CALLS = 5
_DEFAULT_INPUT_TOKEN_BUDGET = 800_000
_DEFAULT_TOOL_RESULT_MAX_BYTES = 16_384


def run_query(question: str, *, history: Optional[list[dict]] = None) -> Optional[str]:
    """Run a tool-calling chat turn and return the model's final text.

    Returns ``None`` when ``GEMINI_API_KEY`` is not set so the caller can
    fall back to local logic. Raises :class:`LLMError` for HTTP failures.
    """
    api_key = _resolve_api_key()
    if api_key is None:
        return None

    model = _resolve_model()
    max_calls = _resolve_max_calls()
    token_budget = _resolve_token_budget()
    tool_result_max_bytes = _resolve_tool_result_max_bytes()
    max_output_tokens = _resolve_max_output_tokens()

    chat_history: History = history if history is not None else []
    chat_history.append({"role": "user", "parts": [{"text": question}]})

    client = GeminiClient(
        api_key=api_key,
        model=model,
        max_output_tokens=max_output_tokens,
    )
    tool_schemas = registry.list_tools()

    total_tokens = 0
    calls_used = 0
    last_text: Optional[str] = None

    while True:
        total_tokens = trimmer.maybe_trim(chat_history, total_tokens, token_budget)

        tools_for_request = tool_schemas if calls_used < max_calls else []
        candidate, usage = client.chat_with_tools(chat_history, tools_for_request)

        reported = usage.get("total_token_count") if usage else None
        if isinstance(reported, int) and reported > 0:
            total_tokens = reported

        parts = candidate.get("parts") or []
        function_calls = [p for p in parts if isinstance(p, dict) and p.get("functionCall")]
        text_parts = [
            p["text"] for p in parts
            if isinstance(p, dict) and isinstance(p.get("text"), str)
        ]

        chat_history.append(candidate)

        if function_calls and calls_used < max_calls:
            for part in function_calls:
                fn_call = part["functionCall"] or {}
                tool_response = executor.invoke(
                    fn_call.get("name", ""),
                    fn_call.get("args"),
                    max_bytes=tool_result_max_bytes,
                )
                chat_history.append(
                    {
                        "role": "user",
                        "parts": [{"functionResponse": tool_response}],
                    }
                )
            calls_used += 1
            continue

        text = "\n".join(t for t in text_parts if t).strip()
        last_text = text or last_text
        return last_text or None


def _resolve_api_key() -> Optional[str]:
    value = os.environ.get("GEMINI_API_KEY")
    if not value:
        return None
    value = value.strip()
    return value or None


def _resolve_model() -> str:
    raw = (os.environ.get("MONIX_LLM_MODEL") or "").strip()
    if not raw:
        return MODEL_FLASH
    lowered = raw.lower()
    if lowered == "pro":
        return MODEL_PRO
    if lowered == "flash":
        return MODEL_FLASH
    if raw in (MODEL_PRO, MODEL_FLASH):
        return raw
    return MODEL_FLASH


def _resolve_max_calls() -> int:
    return _resolve_positive_int("MONIX_LLM_MAX_TOOL_CALLS", _DEFAULT_MAX_CALLS)


def _resolve_token_budget() -> int:
    return _resolve_positive_int("MONIX_LLM_INPUT_TOKEN_BUDGET", _DEFAULT_INPUT_TOKEN_BUDGET)


def _resolve_tool_result_max_bytes() -> int:
    return _resolve_positive_int(
        "MONIX_LLM_TOOL_RESULT_MAX_BYTES",
        _DEFAULT_TOOL_RESULT_MAX_BYTES,
    )


def _resolve_max_output_tokens() -> Optional[int]:
    """Read ``MONIX_LLM_MAX_OUTPUT_TOKENS`` and return an int or ``None``.

    Returning ``None`` lets :class:`GeminiClient` keep its per-method
    built-in defaults (1024 for ``chat``, 2048 for ``chat_with_tools``).
    """
    raw = os.environ.get("MONIX_LLM_MAX_OUTPUT_TOKENS")
    if raw is None:
        return None
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _resolve_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


__all__ = ["run_query"]


# Re-export so ``from monix.llm.runner import LLMError`` keeps working in tests.
_ = LLMError
_ = Any
