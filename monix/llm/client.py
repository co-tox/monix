from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterable, Optional

from monix.llm.prompts import SYSTEM_PROMPT
from monix.llm.types import (
    AuthError,
    History,
    LLMError,
    NetworkError,
    RateLimitError,
    ResponseError,
    ToolSchema,
    UsageInfo,
)


MODEL_PRO = "gemini-3.1-pro-preview"
MODEL_FLASH = "gemini-3.1-flash-preview"

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_HTTP_TIMEOUT = 20


class GeminiClient:
    """Gemini `generateContent` HTTP client.

    Two entry points:
      - `chat(history)`: legacy single-shot call (no tools, no usage info).
      - `chat_with_tools(history, tools)`: tool-calling aware call returning
        the raw first candidate plus usage info.
    """

    def __init__(self, api_key: Optional[str], model: str) -> None:
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat(self, history: History) -> Optional[str]:
        if not self.api_key:
            return None
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": history,
            "generationConfig": {"maxOutputTokens": 1024},
        }
        try:
            data = self._post(payload)
        except LLMError as exc:
            return f"Gemini API 오류: {exc.message}"
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            return None
        for part in parts:
            text = part.get("text") if isinstance(part, dict) else None
            if text:
                return text.strip()
        return None

    def chat_with_tools(
        self,
        history: History,
        tools: Iterable[ToolSchema],
    ) -> tuple[dict, UsageInfo]:
        """Run a tool-calling generateContent call.

        Returns `(candidate_content, usage_info)`. `candidate_content` is the
        raw `{role, parts}` block produced by the model so the caller can
        inspect text / functionCall parts. Raises `LLMError` on failure.
        """
        if not self.api_key:
            raise AuthError("GEMINI_API_KEY is not configured.")

        function_declarations = list(tools)
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": history,
            "generationConfig": {"maxOutputTokens": 2048},
        }
        if function_declarations:
            payload["tools"] = [{"functionDeclarations": function_declarations}]

        data = self._post(payload)
        candidate = self._extract_candidate(data)
        usage = self._extract_usage(data)
        return candidate, usage

    def _post(self, payload: dict) -> dict:
        url = f"{_BASE_URL}/{self.model}:generateContent?key={self.api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            raise self._http_status_error(exc.code, body) from exc
        except urllib.error.URLError as exc:
            raise NetworkError(f"network error: {exc.reason}") from exc
        except (OSError, TimeoutError) as exc:
            raise NetworkError(f"network error: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ResponseError(
                "failed to parse Gemini response",
                body_excerpt=raw[:200],
            ) from exc

    @staticmethod
    def _http_status_error(status: int, body: str) -> LLMError:
        excerpt = body[:200]
        if status in (401, 403):
            return AuthError(
                f"authentication failed ({status})",
                status_code=status,
                body_excerpt=excerpt,
            )
        if status == 429:
            return RateLimitError(
                "rate limit exceeded",
                status_code=status,
                body_excerpt=excerpt,
            )
        return ResponseError(
            f"Gemini API error ({status})",
            status_code=status,
            body_excerpt=excerpt,
        )

    @staticmethod
    def _extract_candidate(data: dict) -> dict:
        try:
            candidates = data["candidates"]
        except KeyError as exc:
            raise ResponseError(
                "Gemini response missing 'candidates'",
                body_excerpt=json.dumps(data)[:200],
            ) from exc
        if not candidates:
            raise ResponseError(
                "Gemini response has no candidates",
                body_excerpt=json.dumps(data)[:200],
            )
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        content = candidate.get("content")
        if content is None:
            if finish in ("MAX_TOKENS", "SAFETY", "RECITATION"):
                raise ResponseError(
                    f"Gemini stopped early: {finish}",
                    body_excerpt=json.dumps(candidate)[:200],
                )
            raise ResponseError(
                "Gemini candidate missing 'content'",
                body_excerpt=json.dumps(candidate)[:200],
            )
        if not isinstance(content, dict):
            raise ResponseError(
                "Gemini candidate 'content' is not an object",
                body_excerpt=json.dumps(candidate)[:200],
            )
        content.setdefault("role", "model")
        content.setdefault("parts", [])
        return content

    @staticmethod
    def _extract_usage(data: dict) -> UsageInfo:
        meta = data.get("usageMetadata") or {}
        return UsageInfo(
            {
                "prompt_token_count": meta.get("promptTokenCount"),
                "candidates_token_count": meta.get("candidatesTokenCount"),
                "total_token_count": meta.get("totalTokenCount"),
            }
        )
