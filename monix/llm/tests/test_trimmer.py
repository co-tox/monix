from __future__ import annotations

from monix.llm import trimmer


def _user(text: str) -> dict:
    return {"role": "user", "parts": [{"text": text}]}


def _model(text: str) -> dict:
    return {"role": "model", "parts": [{"text": text}]}


def _function_call(name: str, args: dict) -> dict:
    return {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}


def _function_response(name: str, response: dict) -> dict:
    return {
        "role": "user",
        "parts": [{"functionResponse": {"name": name, "response": response}}],
    }


def test_no_op_when_under_budget():
    history = [_user("hi"), _model("hello")]
    snapshot = list(history)
    after = trimmer.maybe_trim(history, total_tokens=100, budget=1000)
    assert after == 100
    assert history == snapshot


def test_drops_oldest_pair_when_over_budget():
    history = [
        _user("q1"),
        _model("a1"),
        _user("q2"),
        _model("a2"),
        _user("q3"),
        _model("a3"),
        _user("q4"),
        _model("a4"),
    ]
    after = trimmer.maybe_trim(
        history, total_tokens=10_000, budget=10, recent_keep=2
    )
    pairs_remaining = [m for m in history if m.get("role") == "user"]
    assert _user("q1") not in pairs_remaining
    assert _user("q4") in pairs_remaining
    # Cannot trim into the protected window.
    assert len([m for m in history if m.get("role") == "user"]) >= 2
    assert after >= 0


def test_preserves_recent_pairs():
    history = [_user("q1"), _model("a1"), _user("q2"), _model("a2")]
    trimmer.maybe_trim(history, total_tokens=10_000, budget=1, recent_keep=2)
    assert history == [_user("q1"), _model("a1"), _user("q2"), _model("a2")]


def test_pair_includes_function_call_messages():
    history = [
        _user("q1"),
        _function_call("collect_snapshot", {}),
        _function_response("collect_snapshot", {"ok": True}),
        _model("a1"),
        _user("q2"),
        _model("a2"),
        _user("q3"),
        _model("a3"),
    ]
    trimmer.maybe_trim(history, total_tokens=10_000, budget=10, recent_keep=2)
    # The first pair (with all function-call parts) should be gone wholesale.
    assert _user("q1") not in history
    assert all(
        m.get("parts", [{}])[0].get("functionCall") is None for m in history
        if m.get("role") == "model"
    )
    assert _user("q2") in history and _user("q3") in history


def test_preamble_before_first_user_text_is_kept():
    preamble = {"role": "model", "parts": [{"text": "system warmup"}]}
    history = [
        preamble,
        _user("q1"),
        _model("a1"),
        _user("q2"),
        _model("a2"),
        _user("q3"),
        _model("a3"),
    ]
    trimmer.maybe_trim(history, total_tokens=10_000, budget=10, recent_keep=2)
    assert history[0] is preamble


def test_in_place_mutation():
    history = [_user("q1"), _model("a1"), _user("q2"), _model("a2"), _user("q3"), _model("a3")]
    same_list = history
    trimmer.maybe_trim(history, total_tokens=10_000, budget=10, recent_keep=2)
    assert same_list is history
