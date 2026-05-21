from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from monix.llm.providers.codex import (
    CODEX_RESPONSES_URL,
    CodexClient,
    _history_to_responses_input,
    load_codex_auth,
)
from monix.llm.providers.factory import create_client
from monix.llm.types import AuthError


def _auth_file(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "secret-access-token",
                    "account_id": "acct-test",
                },
            }
        ),
        encoding="utf-8",
    )
    return auth_path


def _success_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return body

    return _Response()


def test_load_codex_auth_reads_tokens_without_exposing_shape(tmp_path):
    auth = load_codex_auth(_auth_file(tmp_path))
    assert auth is not None
    assert auth.access_token == "secret-access-token"
    assert auth.account_id == "acct-test"


def test_codex_client_requires_local_auth(tmp_path):
    client = CodexClient(auth_path=tmp_path / "missing.json")
    assert client.enabled is False
    with pytest.raises(AuthError) as info:
        client.chat_with_tools([{"role": "user", "parts": [{"text": "hi"}]}], [])
    assert "secret" not in str(info.value).lower()
    assert "codex login" in str(info.value)


def test_factory_rejects_unsupported_provider():
    with pytest.raises(AuthError):
        create_client(provider="not-supported", model="anything")


def test_codex_client_adapts_responses_request_and_output(tmp_path):
    client = CodexClient(model="gpt-test", auth_path=_auth_file(tmp_path))
    captured = {}
    payload = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "ready"}],
            }
        ],
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _success_response(payload)

    tools = [
        {
            "name": "collect_snapshot",
            "description": "collect",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        candidate, usage = client.chat_with_tools(
            [{"role": "user", "parts": [{"text": "health"}]}],
            tools,
        )

    assert captured["url"] == CODEX_RESPONSES_URL
    assert captured["body"]["model"] == "gpt-test"
    assert captured["body"]["input"][0]["content"] == "health"
    assert captured["body"]["tools"][0]["type"] == "function"
    assert captured["headers"]["Originator"] == "codex_cli_rs"
    assert captured["headers"]["Chatgpt-account-id"] == "acct-test"
    assert candidate["parts"][0]["text"] == "ready"
    assert usage["total_token_count"] == 6


def test_codex_candidate_preserves_function_call_id(tmp_path):
    client = CodexClient(auth_path=_auth_file(tmp_path))
    payload = {
        "output": [
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "memory_info",
                "arguments": "{}",
            }
        ]
    }
    with patch("urllib.request.urlopen", return_value=_success_response(payload)):
        candidate, _usage = client.chat_with_tools(
            [{"role": "user", "parts": [{"text": "memory"}]}],
            [],
        )
    function_call = candidate["parts"][0]["functionCall"]
    assert function_call["name"] == "memory_info"
    assert function_call["call_id"] == "call-1"


def test_history_adapts_tool_result_to_function_call_output():
    history = [
        {"role": "model", "parts": [{"functionCall": {"name": "memory_info", "args": {}, "call_id": "call-1"}}]},
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "memory_info",
                        "response": {"result": {"used": 1}},
                    }
                }
            ],
        },
    ]
    items = _history_to_responses_input(history)
    assert items[0]["type"] == "function_call"
    assert items[1]["type"] == "function_call_output"
    assert items[1]["call_id"] == "call-1"
