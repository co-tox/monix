from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
import urllib.error

from monix.llm.client import GeminiClient, MODEL_FLASH, MODEL_PRO
from monix.llm.types import (
    AuthError,
    NetworkError,
    RateLimitError,
    ResponseError,
)


_API_KEY = "test-key"


def _success_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")

    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *exc):
            return False

        def read(self_inner):
            return body

    return _Resp()


def _make_http_error(status: int, body: str = "{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example",
        code=status,
        msg="x",
        hdrs={},
        fp=io.BytesIO(body.encode("utf-8")),
    )


def test_model_constants_match_spec():
    assert MODEL_PRO == "gemini-3.1-pro-preview"
    assert MODEL_FLASH == "gemini-3.1-flash-preview"


def test_chat_with_tools_sends_function_declarations():
    client = GeminiClient(_API_KEY, MODEL_FLASH)
    captured = {}

    response_payload = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "ok"}],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"totalTokenCount": 42, "promptTokenCount": 30},
    }

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return _success_response(response_payload)

    tools = [{"name": "noop", "description": "", "parameters": {"type": "object", "properties": {}}}]
    history = [{"role": "user", "parts": [{"text": "hello"}]}]

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        candidate, usage = client.chat_with_tools(history, tools)

    assert MODEL_FLASH in captured["url"]
    assert captured["body"]["tools"] == [{"functionDeclarations": tools}]
    assert captured["body"]["contents"] == history
    assert "system_instruction" in captured["body"]
    assert candidate["parts"][0]["text"] == "ok"
    assert usage["total_token_count"] == 42
    assert usage["prompt_token_count"] == 30


def test_chat_with_tools_omits_tools_when_empty():
    client = GeminiClient(_API_KEY, MODEL_FLASH)
    captured = {}

    payload = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}],
        "usageMetadata": {"totalTokenCount": 1},
    }

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _success_response(payload)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.chat_with_tools([{"role": "user", "parts": [{"text": "hi"}]}], [])

    assert "tools" not in captured["body"]


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, AuthError),
        (403, AuthError),
        (429, RateLimitError),
        (500, ResponseError),
        (503, ResponseError),
        (418, ResponseError),
    ],
)
def test_http_status_maps_to_exception(status, expected):
    client = GeminiClient(_API_KEY, MODEL_FLASH)

    def fake_urlopen(request, timeout):
        raise _make_http_error(status, body="oops")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(expected) as info:
            client.chat_with_tools([{"role": "user", "parts": [{"text": "hi"}]}], [])
    err = info.value
    assert err.status_code == status
    assert err.body_excerpt is not None


def test_url_error_maps_to_network_error():
    client = GeminiClient(_API_KEY, MODEL_FLASH)

    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("dns failure")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(NetworkError):
            client.chat_with_tools([{"role": "user", "parts": [{"text": "hi"}]}], [])


def test_invalid_json_response_raises_response_error():
    client = GeminiClient(_API_KEY, MODEL_FLASH)

    class _BadResp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *exc):
            return False

        def read(self_inner):
            return b"<<<not-json>>>"

    def fake_urlopen(request, timeout):
        return _BadResp()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(ResponseError):
            client.chat_with_tools([{"role": "user", "parts": [{"text": "hi"}]}], [])


def test_chat_with_tools_requires_api_key():
    client = GeminiClient(None, MODEL_FLASH)
    with pytest.raises(AuthError):
        client.chat_with_tools([{"role": "user", "parts": [{"text": "hi"}]}], [])


def test_legacy_chat_returns_none_without_key():
    client = GeminiClient(None, MODEL_FLASH)
    assert client.chat([{"role": "user", "parts": [{"text": "hi"}]}]) is None


def test_legacy_chat_extracts_text():
    client = GeminiClient(_API_KEY, MODEL_FLASH)
    payload = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": "  hi  "}]}}],
    }

    def fake_urlopen(request, timeout):
        return _success_response(payload)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = client.chat([{"role": "user", "parts": [{"text": "hi"}]}])
    assert out == "hi"
