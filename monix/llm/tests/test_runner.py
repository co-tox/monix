from __future__ import annotations

from unittest.mock import patch

import pytest

from monix.llm import runner
from monix.llm.client import MODEL_FLASH, MODEL_PRO


def test_resolve_api_key_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert runner._resolve_api_key() is None


def test_resolve_api_key_blank(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert runner._resolve_api_key() is None


def test_resolve_api_key_set(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    assert runner._resolve_api_key() == "abc"


def test_resolve_model_default(monkeypatch):
    monkeypatch.delenv("MONIX_LLM_MODEL", raising=False)
    assert runner._resolve_model() == MODEL_FLASH


def test_resolve_model_alias_pro(monkeypatch):
    monkeypatch.setenv("MONIX_LLM_MODEL", "pro")
    assert runner._resolve_model() == MODEL_PRO


def test_resolve_model_alias_flash(monkeypatch):
    monkeypatch.setenv("MONIX_LLM_MODEL", "flash")
    assert runner._resolve_model() == MODEL_FLASH


def test_resolve_model_full_id(monkeypatch):
    monkeypatch.setenv("MONIX_LLM_MODEL", MODEL_PRO)
    assert runner._resolve_model() == MODEL_PRO


def test_resolve_model_unknown_falls_back(monkeypatch):
    monkeypatch.setenv("MONIX_LLM_MODEL", "gpt-99")
    assert runner._resolve_model() == MODEL_FLASH


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, 5),
        ("", 5),
        ("not-a-number", 5),
        ("0", 5),
        ("-3", 5),
        ("12", 12),
    ],
)
def test_resolve_max_calls(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MONIX_LLM_MAX_TOOL_CALLS", raising=False)
    else:
        monkeypatch.setenv("MONIX_LLM_MAX_TOOL_CALLS", value)
    assert runner._resolve_max_calls() == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, 800_000),
        ("garbage", 800_000),
        ("1024", 1024),
    ],
)
def test_resolve_token_budget(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MONIX_LLM_INPUT_TOKEN_BUDGET", raising=False)
    else:
        monkeypatch.setenv("MONIX_LLM_INPUT_TOKEN_BUDGET", value)
    assert runner._resolve_token_budget() == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, 16_384),
        ("garbage", 16_384),
        ("4096", 4096),
    ],
)
def test_resolve_tool_result_max_bytes(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MONIX_LLM_TOOL_RESULT_MAX_BYTES", raising=False)
    else:
        monkeypatch.setenv("MONIX_LLM_TOOL_RESULT_MAX_BYTES", value)
    assert runner._resolve_tool_result_max_bytes() == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        ("garbage", None),
        ("0", None),
        ("-5", None),
        ("4096", 4096),
    ],
)
def test_resolve_max_output_tokens(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MONIX_LLM_MAX_OUTPUT_TOKENS", raising=False)
    else:
        monkeypatch.setenv("MONIX_LLM_MAX_OUTPUT_TOKENS", value)
    assert runner._resolve_max_output_tokens() == expected


def test_run_query_returns_none_when_no_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    history: list[dict] = []
    assert runner.run_query("hi", history=history) is None
    assert history == []


def _text_candidate(text: str) -> dict:
    return {"role": "model", "parts": [{"text": text}]}


def _function_call_candidate(name: str, args: dict) -> dict:
    return {
        "role": "model",
        "parts": [{"functionCall": {"name": name, "args": args}}],
    }


def test_run_query_text_only_round_trip(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.delenv("MONIX_LLM_MODEL", raising=False)
    monkeypatch.delenv("MONIX_LLM_MAX_TOOL_CALLS", raising=False)
    monkeypatch.delenv("MONIX_LLM_INPUT_TOKEN_BUDGET", raising=False)

    calls = []

    def fake_chat_with_tools(self, history, tools):
        calls.append({"history_len": len(history), "tools": list(tools)})
        return _text_candidate("hello operator"), {"total_token_count": 100}

    history: list[dict] = []
    with patch("monix.llm.client.GeminiClient.chat_with_tools", new=fake_chat_with_tools):
        result = runner.run_query("ping", history=history)

    assert result == "hello operator"
    assert calls and calls[0]["history_len"] == 1
    # User question + model response are accumulated.
    roles = [m["role"] for m in history]
    assert roles == ["user", "model"]
    assert history[1]["parts"][0]["text"] == "hello operator"


def test_run_query_executes_tool_call_then_answers(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.delenv("MONIX_LLM_MAX_TOOL_CALLS", raising=False)

    sequence = [
        (_function_call_candidate("classify_line", {"line": "ERROR boom"}), {"total_token_count": 200}),
        (_text_candidate("classified"), {"total_token_count": 250}),
    ]
    iterator = iter(sequence)

    def fake_chat_with_tools(self, history, tools):
        return next(iterator)

    history: list[dict] = []
    with patch("monix.llm.client.GeminiClient.chat_with_tools", new=fake_chat_with_tools):
        result = runner.run_query("classify a line", history=history)

    assert result == "classified"
    roles = [m.get("role") for m in history]
    # user question, model functionCall, user functionResponse, model text
    assert roles == ["user", "model", "user", "model"]
    fc = history[1]["parts"][0]["functionCall"]
    assert fc["name"] == "classify_line"
    fr = history[2]["parts"][0]["functionResponse"]
    assert fr["name"] == "classify_line"
    assert "measured_at" in fr["response"]


def test_run_query_max_calls_disables_tools(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setenv("MONIX_LLM_MAX_TOOL_CALLS", "1")

    captured_tool_lists = []

    def fake_chat_with_tools(self, history, tools):
        captured_tool_lists.append(list(tools))
        # First call: requests a tool. Second call (after the limit) should
        # see no tools and return text.
        if len(captured_tool_lists) == 1:
            return _function_call_candidate("classify_line", {"line": "ERROR x"}), {"total_token_count": 100}
        return _text_candidate("final"), {"total_token_count": 110}

    history: list[dict] = []
    with patch("monix.llm.client.GeminiClient.chat_with_tools", new=fake_chat_with_tools):
        result = runner.run_query("look", history=history)

    assert result == "final"
    assert captured_tool_lists[0]  # tools enabled on the first call
    assert captured_tool_lists[1] == []  # disabled on the second call


def test_run_query_token_budget_triggers_trim(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setenv("MONIX_LLM_INPUT_TOKEN_BUDGET", "1")  # tiny budget

    pre_existing_pairs = []
    for i in range(4):
        pre_existing_pairs.append({"role": "user", "parts": [{"text": f"q{i}"}]})
        pre_existing_pairs.append({"role": "model", "parts": [{"text": f"a{i}"}]})

    sequence = [
        # First call surfaces a function call so the loop iterates again,
        # giving the trimmer a chance to run with the reported token count.
        (_function_call_candidate("classify_line", {"line": "ERROR boom"}), {"total_token_count": 10_000}),
        (_text_candidate("ok"), {"total_token_count": 10_500}),
    ]
    iterator = iter(sequence)

    def fake_chat_with_tools(self, history, tools):
        return next(iterator)

    history = list(pre_existing_pairs)
    with patch("monix.llm.client.GeminiClient.chat_with_tools", new=fake_chat_with_tools):
        runner.run_query("now", history=history)

    user_texts = [
        m["parts"][0].get("text") for m in history
        if m.get("role") == "user" and m.get("parts", [{}])[0].get("text")
    ]
    # The earliest pair(s) should have been dropped on the second iteration's pre-call trim.
    assert "q0" not in user_texts
