from __future__ import annotations

import json
import urllib.error
import urllib.request


SYSTEM_PROMPT = """You are Monix, a terminal server monitoring assistant.
You help operators understand server health from read-only telemetry.
Be concise, practical, and explicit about risk. Do not suggest destructive commands.
When data is missing, say what is missing and give a low-risk next check.

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


class AnthropicClient:
    def __init__(self, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def analyze_snapshot(self, question: str, snapshot: dict) -> str | None:
        if not self.api_key:
            return None
        payload = {
            "model": self.model,
            "max_tokens": 900,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Operator question:\n{question}\n\n"
                        f"Current server snapshot JSON:\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}"
                    ),
                }
            ],
        }
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            return f"Anthropic API call failed: {exc}"
        parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts).strip() or None
