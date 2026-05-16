from __future__ import annotations

import json
import urllib.error
import urllib.request


def _post_json(url: str, payload: dict, timeout: int = 5) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "monix-webhook/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            pass
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        hint = _http_hint(e.code)
        msg = f"HTTP {e.code} {e.reason}"
        if body:
            msg += f" — {body}"
        if hint:
            msg += f"\n  Hint: {hint}"
        raise RuntimeError(msg) from e


def _http_hint(code: int) -> str:
    if code == 403:
        return "Webhook URL may be invalid or the webhook was deleted. Verify MONIX_DISCORD_WEBHOOK / MONIX_SLACK_WEBHOOK."
    if code == 404:
        return "Webhook not found. The webhook may have been deleted."
    if code == 400:
        return "Bad request — check that the webhook URL is correct."
    if code == 429:
        return "Rate limited by the server. Try again later."
    return ""
