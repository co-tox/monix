from __future__ import annotations

import json
import urllib.error
import urllib.request


SYSTEM_PROMPT = """You are Monix, a terminal server monitoring assistant.
You help operators understand server health from read-only telemetry.
Be concise, practical, and explicit about risk. Do not suggest destructive commands.
When data is missing, say what is missing and give a low-risk next check.
Respond in the same language the user writes in (Korean if they write Korean)."""


class GeminiClient:
    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat(self, history: list[dict]) -> str | None:
        if not self.api_key:
            return None
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": history,
            "generationConfig": {"maxOutputTokens": 1024},
        }
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
            return f"Gemini API 오류 ({exc.code}): {body[:200]}"
        except (OSError, urllib.error.URLError) as exc:
            return f"Gemini API 호출에 실패했습니다: {exc}"
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError):
            return None
