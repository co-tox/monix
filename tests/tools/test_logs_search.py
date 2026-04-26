"""Tests for search_log (app.py) and the natural-language @alias routing in cli.py."""
import re
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from monix.tools.logs.app import search_log


# ── search_log ────────────────────────────────────────────────────────────────

def test_search_log_missing_file(tmp_path):
    result = search_log(tmp_path / "nope.log")
    assert result["status"] == "missing"
    assert result["matches"] == []
    assert result["total_scanned"] == 0


def test_search_log_not_a_file(tmp_path):
    result = search_log(tmp_path)
    assert result["status"] == "not_file"


def test_search_log_error_filter_finds_errors(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("INFO: ok\nERROR: boom\nDEBUG: fine\nWARN: almost\n")
    with patch("monix.tools.logs.app.subprocess.check_output", return_value="INFO: ok\nERROR: boom\nDEBUG: fine\nWARN: almost"):
        result = search_log(log)
    assert result["status"] == "ok"
    assert result["query"] is None
    severities = {m["severity"] for m in result["matches"]}
    assert severities <= {"error", "warn"}
    assert any(m["severity"] == "error" for m in result["matches"])


def test_search_log_error_filter_no_matches(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("INFO: all good\nDEBUG: nothing\n")
    with patch("monix.tools.logs.app.subprocess.check_output", return_value="INFO: all good\nDEBUG: nothing"):
        result = search_log(log)
    assert result["matches"] == []
    assert result["total_scanned"] == 2


def test_search_log_pattern_match(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("INFO: connected\nERROR: timeout waiting for db\nINFO: retry\n")
    with patch("monix.tools.logs.app.subprocess.check_output",
               return_value="INFO: connected\nERROR: timeout waiting for db\nINFO: retry"):
        result = search_log(log, pattern="timeout")
    assert result["query"] == "timeout"
    assert len(result["matches"]) == 1
    assert "timeout" in result["matches"][0]["line"]


def test_search_log_pattern_case_insensitive(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("TIMEOUT\ntimeout\nTimeOut\nnope\n")
    with patch("monix.tools.logs.app.subprocess.check_output",
               return_value="TIMEOUT\ntimeout\nTimeOut\nnope"):
        result = search_log(log, pattern="timeout")
    assert len(result["matches"]) == 3


def test_search_log_invalid_regex_falls_back_to_literal(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("err[or\nok\n")
    with patch("monix.tools.logs.app.subprocess.check_output", return_value="err[or\nok"):
        result = search_log(log, pattern="err[or")
    assert result["status"] == "ok"
    assert len(result["matches"]) == 1


def test_search_log_lineno_correct(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("line1\nline2\nERROR: line3\nline4\n")
    output = "line1\nline2\nERROR: line3\nline4"
    with patch("monix.tools.logs.app.subprocess.check_output", return_value=output):
        result = search_log(log)
    match = result["matches"][0]
    assert match["lineno"] == 3


def test_search_log_total_scanned(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("placeholder")
    output = "\n".join(f"line{i}" for i in range(10))
    with patch("monix.tools.logs.app.subprocess.check_output", return_value=output):
        result = search_log(log, pattern="line1")
    assert result["total_scanned"] == 10


def test_search_log_subprocess_error(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("data")
    with patch("monix.tools.logs.app.subprocess.check_output", side_effect=OSError("fail")):
        result = search_log(log)
    assert result["status"] == "error"


# ── _detect_log_alias ─────────────────────────────────────────────────────────

def test_detect_log_alias_found(tmp_path, monkeypatch):
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)
    reg_file.parent.mkdir(parents=True)
    reg_file.write_text(json.dumps([{"alias": "api", "type": "app", "path": "/x.log", "container": None}]))

    from monix.cli import _detect_log_alias
    assert _detect_log_alias("@api 로그 에러 확인해줘") == "api"


def test_detect_log_alias_not_registered(tmp_path, monkeypatch):
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)

    from monix.cli import _detect_log_alias
    assert _detect_log_alias("@ghost 로그 에러 확인해줘") is None


def test_detect_log_alias_no_at_sign():
    from monix.cli import _detect_log_alias
    assert _detect_log_alias("로그 에러 확인해줘") is None


# ── _extract_search_pattern ───────────────────────────────────────────────────

def test_extract_pattern_quoted():
    from monix.cli import _extract_search_pattern
    assert _extract_search_pattern('@api "timeout" 에러 찾아줘', "api") == "timeout"


def test_extract_pattern_english_keyword():
    from monix.cli import _extract_search_pattern
    result = _extract_search_pattern("@api timeout 에러 찾아줘", "api")
    assert result == "timeout"


def test_extract_pattern_numeric_keyword():
    from monix.cli import _extract_search_pattern
    result = _extract_search_pattern("@nginx 500 에러 검색해줘", "nginx")
    assert result == "500"


def test_extract_pattern_returns_none_for_pure_intent():
    from monix.cli import _extract_search_pattern
    result = _extract_search_pattern("@api 로그를 검색해서 에러가 있는지 확인해줘", "api")
    assert result is None


# ── _detect_log_intent ───────────────────────────────────────────────────────

def test_detect_intent_tail_for_last_lines():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("@application 로그 마지막 줄 검색해서 출력해줘") == "tail"


def test_detect_intent_tail_for_show():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("@api 로그 보여줘") == "tail"


def test_detect_intent_search_for_error():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("@api 로그를 검색해서 에러가 있는지 확인해줘") == "search"


def test_detect_intent_search_for_오류():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("@nginx 오류 있는지 봐줘") == "search"


def test_detect_intent_default_tail():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("@api 로그") == "tail"


# ── _extract_lines_count ──────────────────────────────────────────────────────

def test_extract_lines_마지막_N줄():
    from monix.cli import _extract_lines_count
    assert _extract_lines_count("마지막 100줄 보여줘") == 100


def test_extract_lines_last_N_lines():
    from monix.cli import _extract_lines_count
    assert _extract_lines_count("last 50 lines") == 50


def test_extract_lines_default():
    from monix.cli import _extract_lines_count
    assert _extract_lines_count("에러 확인해줘") == 80


def test_extract_lines_N줄_앞에_마지막_없이():
    from monix.cli import _extract_lines_count
    assert _extract_lines_count("200줄 출력해줘") == 200


# ── _log_search_natural (integration) ────────────────────────────────────────

def test_log_search_natural_alias_not_found(tmp_path, monkeypatch):
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)

    from monix.cli import _log_search_natural
    result = _log_search_natural("ghost", "@ghost 에러 확인해줘")
    assert "등록되어 있지 않습니다" in result


def test_log_search_natural_tail_intent(tmp_path, monkeypatch):
    """'마지막 줄 출력' → tail_log, not error search."""
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)
    reg_file.parent.mkdir(parents=True)
    log_file = tmp_path / "app.log"
    log_file.write_text("INFO: all good\n")
    reg_file.write_text(json.dumps([{"alias": "application", "type": "app", "path": str(log_file), "container": None}]))

    with patch("monix.tools.logs.app.subprocess.check_output", return_value="INFO: all good"):
        from monix.cli import _log_search_natural
        result = _log_search_natural("application", "@application 로그 마지막 줄 검색해서 출력해줘")
    # Should render as a plain log view, not error-search result
    assert "에러/경고" not in result
    assert "Log:" in result


def test_log_search_natural_error_filter(tmp_path, monkeypatch):
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)
    reg_file.parent.mkdir(parents=True)
    log_file = tmp_path / "api.log"
    log_file.write_text("INFO: ok\nERROR: crash\nDEBUG: fine\n")
    reg_file.write_text(json.dumps([{"alias": "api", "type": "app", "path": str(log_file), "container": None}]))

    fake_output = "INFO: ok\nERROR: crash\nDEBUG: fine"
    with patch("monix.tools.logs.app.subprocess.check_output", return_value=fake_output):
        from monix.cli import _log_search_natural
        result = _log_search_natural("api", "@api 로그를 검색해서 에러가 있는지 확인해줘")
    assert "에러/경고" in result
    assert "crash" in result
