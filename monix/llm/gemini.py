from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from monix.tools.calling import ToolCall


SYSTEM_PROMPT = """You are Monix, a terminal server monitoring assistant.
You help operators understand server health from read-only telemetry.
Be concise, practical, and explicit about risk. Do not suggest destructive commands.
When data is missing, say what is missing and give a low-risk next check.
Respond in the same language the user writes in (Korean if they write Korean).
When you need log or service data not present in the snapshot, use the available tools.

Monix is controlled via slash commands in the terminal. When users ask how to do something in Monix, guide them with the correct command:

Log management:
  /log add @alias -app <path>      Register an application log file
  /log add @alias -nginx <path>    Register a Nginx log file
  /log add @alias -docker <name>   Register a Docker container log
  /log remove @alias               Unregister a log
  /log list                        Show registered logs
  /log @alias [-n N]               View last N lines of a registered log
  /log @alias --search [pattern]   Search a registered log for errors or pattern
  /log @alias --live               Stream a registered log in real-time"""


class GeminiClient:
    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def validate(api_key: str, model: str = "gemini-1.5-flash") -> tuple[bool, str]:
        """Returns (is_valid, error_message). error_message is empty on success."""
        url = f"{GeminiClient._BASE}?key={api_key}"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10):
                return True, ""
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return False, f"HTTP {exc.code}: {body[:120]}"
        except (urllib.error.URLError, OSError) as exc:
            return False, str(exc)

    def chat(self, history: list[dict]) -> str | None:
        """Plain chat without tool calling (legacy / fallback)."""
        text, _, _ = self.chat_with_tools(history, [])
        return text

    def chat_with_tools(
        self,
        history: list[dict],
        tool_declarations: list[dict],
    ) -> tuple[str | None, list[ToolCall], list[dict]]:
        """Send a message and return (text_response, tool_calls, raw_model_parts).

        Per round, exactly one will be populated:
        - tool_calls non-empty → LLM wants to call tools; text is None.
        - tool_calls empty    → LLM produced a final answer; text is set.
        raw_model_parts is the verbatim parts list from the API response — callers
        must use it as-is when appending to history so that thought_signature and
        other model-internal fields required by thinking models are preserved.
        On API error returns (error_message, [], []).
        """
        from monix.tools.calling import ToolCall as _ToolCall

        if not self.api_key:
            return None, [], []

        payload: dict = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": history,
            "generationConfig": {"maxOutputTokens": 1024},
        }
        if tool_declarations:
            payload["tools"] = [{"function_declarations": tool_declarations}]
            payload["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}

        url = f"{self._BASE}/{self.model}:generateContent?key={self.api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return f"Gemini API 오류 ({exc.code}): {body[:200]}", [], []
        except (OSError, urllib.error.URLError) as exc:
            return f"Gemini API 호출에 실패했습니다: {exc}", [], []

        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            return None, [], []

        text_parts: list[str] = []
        tool_calls: list[_ToolCall] = []
        for part in parts:
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(_ToolCall(name=fc["name"], args=fc.get("args") or {}))
            elif "text" in part:
                text_parts.append(part["text"])

        return "\n".join(text_parts).strip() or None, tool_calls, parts
