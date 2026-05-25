from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
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


DEFAULT_CODEX_MODEL = "gpt-5.5"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
_HTTP_TIMEOUT = 60


@dataclass(frozen=True)
class CodexAuth:
    access_token: str
    account_id: Optional[str] = None


class CodexClient:
    """Responses adapter for Codex CLI OAuth credentials."""

    def __init__(
        self,
        model: str = DEFAULT_CODEX_MODEL,
        *,
        auth_path: Path | str = DEFAULT_CODEX_AUTH_PATH,
        max_output_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.model = model or DEFAULT_CODEX_MODEL
        self.auth_path = Path(auth_path).expanduser()
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout if timeout is not None else _HTTP_TIMEOUT
        self._auth = load_codex_auth(self.auth_path)

    @property
    def enabled(self) -> bool:
        return self._auth is not None

    def chat(self, history: History) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            candidate, _usage = self.chat_with_tools(history, [])
        except LLMError as exc:
            return f"OpenAI Codex API error: {exc.message}"
        return _candidate_text(candidate)

    def chat_with_tools(
        self,
        history: History,
        tools: Iterable[ToolSchema],
    ) -> tuple[dict, UsageInfo]:
        if self._auth is None:
            raise AuthError(
                "Codex auth is unavailable. Install Codex CLI and run `codex login`."
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": SYSTEM_PROMPT,
            "input": _history_to_responses_input(history),
            "store": False,
            "stream": True,
        }
        response_tools = [_to_response_tool(tool) for tool in tools]
        if response_tools:
            payload["tools"] = response_tools
        if self.max_output_tokens is not None:
            payload["max_output_tokens"] = self.max_output_tokens

        data = self._post(payload)
        return _extract_candidate(data), _extract_usage(data)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._auth is not None
        headers = {
            "accept": "text/event-stream",
            "authorization": f"Bearer {self._auth.access_token}",
            "content-type": "application/json",
            "originator": "codex_cli_rs",
            "user-agent": "codex_cli_rs/monix",
        }
        if self._auth.account_id:
            headers["ChatGPT-Account-ID"] = self._auth.account_id
        request = urllib.request.Request(
            CODEX_RESPONSES_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            raise _http_status_error(exc.code, body) from exc
        except urllib.error.URLError as exc:
            raise NetworkError(f"network error: {exc.reason}") from exc
        except (OSError, TimeoutError) as exc:
            raise NetworkError(f"network error: {exc}") from exc

        data = _parse_response(raw)
        if not isinstance(data, dict):
            raise ResponseError("Codex response is not an object")
        return data


def load_codex_auth(path: Path = DEFAULT_CODEX_AUTH_PATH) -> Optional[CodexAuth]:
    try:
        raw = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    tokens = raw.get("tokens")
    if not isinstance(tokens, dict):
        return None
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    account_id = tokens.get("account_id")
    return CodexAuth(
        access_token=access_token.strip(),
        account_id=account_id.strip() if isinstance(account_id, str) and account_id.strip() else None,
    )


def _parse_response(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _parse_stream_response(raw)
    if not isinstance(data, dict):
        raise ResponseError("Codex response is not an object")
    return data


def _parse_stream_response(raw: str) -> dict[str, Any]:
    completed: dict[str, Any] | None = None
    failed: dict[str, Any] | None = None
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        event_data = line.removeprefix("data:").strip()
        if not event_data or event_data == "[DONE]":
            continue
        try:
            event = json.loads(event_data)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        response = event.get("response")
        if event.get("type") == "response.completed" and isinstance(response, dict):
            completed = response
        elif event.get("type") in ("response.failed", "error") and isinstance(event, dict):
            failed = event
    if completed is not None:
        return completed
    if failed is not None:
        raise ResponseError(
            "Codex stream failed",
            body_excerpt=json.dumps(failed)[:200],
        )
    raise ResponseError(
        "failed to parse Codex stream response",
        body_excerpt=raw[:200],
    )


def _to_response_tool(tool: ToolSchema) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
    }


def _history_to_responses_input(history: History) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    pending_calls: dict[str, list[str]] = {}
    for message in history:
        role = message.get("role")
        parts = message.get("parts") or []
        text_parts: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
                continue
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                call_id = str(function_call.get("call_id") or f"call_{len(items)}")
                name = str(function_call.get("name") or "")
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": name,
                        "arguments": json.dumps(function_call.get("args") or {}),
                    }
                )
                pending_calls.setdefault(name, []).append(call_id)
                continue
            function_response = part.get("functionResponse")
            if isinstance(function_response, dict):
                name = str(function_response.get("name") or "")
                call_ids = pending_calls.get(name) or []
                call_id = call_ids.pop(0) if call_ids else f"call_{len(items)}"
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(function_response.get("response") or {}),
                    }
                )
        if text_parts:
            items.append(
                {
                    "role": "assistant" if role == "model" else "user",
                    "content": "\n".join(text_parts),
                }
            )
    return items


def _extract_candidate(data: dict[str, Any]) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            args = item.get("arguments")
            try:
                parsed_args = json.loads(args) if isinstance(args, str) and args else {}
            except json.JSONDecodeError:
                parsed_args = {}
            parts.append(
                {
                    "functionCall": {
                        "name": item.get("name", ""),
                        "args": parsed_args,
                        "call_id": item.get("call_id", ""),
                    }
                }
            )
            continue
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") not in ("output_text", "text"):
                continue
            text = content.get("text")
            if isinstance(text, str) and text:
                parts.append({"text": text})
    output_text = data.get("output_text")
    if not parts and isinstance(output_text, str) and output_text:
        parts.append({"text": output_text})
    if not parts:
        raise ResponseError(
            "Codex response did not include text or function calls",
            body_excerpt=json.dumps(data)[:200],
        )
    return {"role": "model", "parts": parts}


def _extract_usage(data: dict[str, Any]) -> UsageInfo:
    usage = data.get("usage") or {}
    return UsageInfo(
        {
            "prompt_token_count": usage.get("input_tokens"),
            "candidates_token_count": usage.get("output_tokens"),
            "total_token_count": usage.get("total_tokens"),
        }
    )


def _candidate_text(candidate: dict[str, Any]) -> Optional[str]:
    text = "\n".join(
        part["text"]
        for part in candidate.get("parts") or []
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()
    return text or None


def _http_status_error(status: int, body: str) -> LLMError:
    excerpt = body[:200]
    if status in (401, 403):
        return AuthError(
            f"Codex authentication failed ({status}); run `codex login` again.",
            status_code=status,
            body_excerpt=excerpt,
        )
    if status == 429:
        return RateLimitError(
            "Codex rate limit exceeded",
            status_code=status,
            body_excerpt=excerpt,
        )
    return ResponseError(
        f"Codex API error ({status})",
        status_code=status,
        body_excerpt=excerpt,
    )
