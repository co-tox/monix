from __future__ import annotations

import json

import pytest

from monix.llm import executor, registry


_BIG_BYTES = 1024


def test_unknown_tool_returns_error():
    response = executor.invoke("does_not_exist", {}, max_bytes=_BIG_BYTES)
    assert response["name"] == "does_not_exist"
    assert "error" in response["response"]
    assert "unknown tool" in response["response"]["error"]


def test_missing_required_arg_returns_error(monkeypatch):
    response = executor.invoke("service_status", {}, max_bytes=_BIG_BYTES)
    assert "error" in response["response"]
    assert "missing required argument" in response["response"]["error"]


def test_unexpected_arg_returns_error(monkeypatch):
    def fake_tool(name: str) -> dict:
        return {"name": name}

    monkeypatch.setattr(registry, "get_tool", lambda n: fake_tool if n == "fake_tool" else None)
    response = executor.invoke(
        "fake_tool", {"name": "ok", "extra": "boom"}, max_bytes=_BIG_BYTES
    )
    assert "error" in response["response"]
    assert "unexpected argument" in response["response"]["error"]


def test_runtime_exception_returns_error(monkeypatch):
    def boom() -> dict:
        raise RuntimeError("kapow")

    monkeypatch.setattr(registry, "get_tool", lambda n: boom if n == "boom" else None)
    response = executor.invoke("boom", {}, max_bytes=_BIG_BYTES)
    assert "error" in response["response"]
    assert "RuntimeError" in response["response"]["error"]
    assert "kapow" in response["response"]["error"]


def test_measured_at_is_added(monkeypatch):
    def ok() -> dict:
        return {"value": 1}

    monkeypatch.setattr(registry, "get_tool", lambda n: ok if n == "ok" else None)
    response = executor.invoke("ok", {}, max_bytes=_BIG_BYTES)
    payload = response["response"]
    assert payload["value"] == 1
    assert "measured_at" in payload
    assert payload["measured_at"].endswith("Z")


def test_measured_at_prefers_existing_timestamp(monkeypatch):
    def ok() -> dict:
        return {"value": 2, "timestamp": "2024-01-01T00:00:00Z"}

    monkeypatch.setattr(registry, "get_tool", lambda n: ok if n == "ok" else None)
    response = executor.invoke("ok", {}, max_bytes=_BIG_BYTES)
    payload = response["response"]
    assert payload["measured_at"] == "2024-01-01T00:00:00Z"


def test_truncation_adds_meta(monkeypatch):
    def big() -> dict:
        return {"blob": "x" * 5000}

    monkeypatch.setattr(registry, "get_tool", lambda n: big if n == "big" else None)
    response = executor.invoke("big", {}, max_bytes=512)
    payload = response["response"]
    assert payload["_truncated"] is True
    assert payload["_original_size_bytes"] > 512
    assert "_preview" in payload
    assert isinstance(payload["_preview"], str)


def test_masking_applied_to_tool_result(monkeypatch):
    def secret_tool() -> dict:
        return {"line": 'API_KEY="hunter2leak"'}

    monkeypatch.setattr(registry, "get_tool", lambda n: secret_tool if n == "s" else None)
    response = executor.invoke("s", {}, max_bytes=_BIG_BYTES)
    serialized = json.dumps(response["response"])
    assert "hunter2leak" not in serialized
    assert "***" in serialized


def test_generator_result_returns_error(monkeypatch):
    def gen():
        yield "line"

    monkeypatch.setattr(registry, "get_tool", lambda n: gen if n == "gen" else None)
    response = executor.invoke("gen", {}, max_bytes=_BIG_BYTES)
    assert "error" in response["response"]
    assert "stream" in response["response"]["error"]


def test_non_jsonable_result_is_coerced(monkeypatch):
    class Custom:
        def __repr__(self) -> str:
            return "<Custom>"

    def quirky() -> dict:
        return {"obj": Custom()}

    monkeypatch.setattr(registry, "get_tool", lambda n: quirky if n == "q" else None)
    response = executor.invoke("q", {}, max_bytes=_BIG_BYTES)
    payload = response["response"]
    assert payload["obj"] == "<Custom>"


def test_classify_line_round_trip():
    response = executor.invoke(
        "classify_line", {"line": "ERROR: something broke"}, max_bytes=_BIG_BYTES
    )
    payload = response["response"]
    assert payload.get("result") == "error"
    assert "measured_at" in payload
