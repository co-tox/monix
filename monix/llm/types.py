from __future__ import annotations

from typing import Any, Dict, List, Optional


Message = Dict[str, Any]
History = List[Message]
ToolCall = Dict[str, Any]
ToolResponse = Dict[str, Any]
ToolSchema = Dict[str, Any]


class UsageInfo(Dict[str, Any]):
    """`{prompt_token_count, candidates_token_count, total_token_count}` shape.

    Stored as plain dict for serialization friendliness.
    """


class LLMError(Exception):
    """Base class for monix.llm errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        body_excerpt: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body_excerpt = body_excerpt

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(message={self.message!r}, "
            f"status_code={self.status_code!r}, body_excerpt={self.body_excerpt!r})"
        )


class AuthError(LLMError):
    """401 / 403 from the provider."""


class RateLimitError(LLMError):
    """429 from the provider."""


class NetworkError(LLMError):
    """`urllib`/`OSError`/timeout."""


class ResponseError(LLMError):
    """5xx, other 4xx, response parse failure, token-limit responses."""


class ToolError(LLMError):
    """Unrecoverable tool registration/execution failure."""
