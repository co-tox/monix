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
    assert _detect_log_alias("check @api log errors") == "api"


def test_detect_log_alias_not_registered(tmp_path, monkeypatch):
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)

    from monix.cli import _detect_log_alias
    assert _detect_log_alias("check @ghost log errors") is None


def test_detect_log_alias_no_at_sign():
    from monix.cli import _detect_log_alias
    assert _detect_log_alias("check log errors") is None


def test_detect_log_alias_with_punctuation(tmp_path, monkeypatch):
    """@alias. - Punctuation after alias should still resolve."""
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)
    reg_file.parent.mkdir(parents=True)
    reg_file.write_text(json.dumps([{"alias": "application", "type": "app", "path": "/x.log", "container": None}]))

    from monix.cli import _detect_log_alias
    assert _detect_log_alias("show @application.") == "application"


# ── _extract_search_pattern ───────────────────────────────────────────────────

def test_extract_pattern_quoted():
    from monix.cli import _extract_search_pattern
    assert _extract_search_pattern('find "timeout" errors in @api', "api") == "timeout"


def test_extract_pattern_english_keyword():
    from monix.cli import _extract_search_pattern
    result = _extract_search_pattern("find timeout error in @api", "api")
    assert result == "timeout"


def test_extract_pattern_numeric_keyword():
    from monix.cli import _extract_search_pattern
    result = _extract_search_pattern("search @nginx for 500 errors", "nginx")
    assert result == "500"


def test_extract_pattern_returns_none_for_pure_intent():
    from monix.cli import _extract_search_pattern
    result = _extract_search_pattern("search @api logs to see if there are errors", "api")
    assert result is None


def test_extract_pattern_mixed_ascii_punctuation():
    from monix.cli import _extract_search_pattern
    result = _extract_search_pattern("show last lines of @application:warn", "application")
    assert result == "warn"


# ── _is_bare_alias_input ─────────────────────────────────────────────────────

def test_is_bare_alias_just_alias():
    from monix.cli import _is_bare_alias_input
    assert _is_bare_alias_input("@application", "application") is True


def test_is_bare_alias_with_punctuation():
    from monix.cli import _is_bare_alias_input
    assert _is_bare_alias_input("@application.", "application") is True


def test_is_bare_alias_with_only_stopword():
    from monix.cli import _is_bare_alias_input
    assert _is_bare_alias_input("@application log", "application") is True


def test_is_bare_alias_with_intent_word():
    from monix.cli import _is_bare_alias_input
    assert _is_bare_alias_input("@application check errors", "application") is False


def test_is_bare_alias_with_search_pattern():
    from monix.cli import _is_bare_alias_input
    assert _is_bare_alias_input("@application timeout", "application") is False


# ── _is_natural_question ─────────────────────────────────────────────────────

def test_is_natural_question_with_question_mark():
    from monix.cli import _is_natural_question
    assert _is_natural_question("Are there any success logs in @application?") is True


def test_is_natural_question_with_polite_request():
    from monix.cli import _is_natural_question
    assert _is_natural_question("please show me one @application log") is True


def test_is_natural_question_imperative_command_is_not():
    from monix.cli import _is_natural_question
    assert _is_natural_question("check @api errors") is False


def test_is_natural_question_tail_command_is_not():
    from monix.cli import _is_natural_question
    assert _is_natural_question("show last 50 lines of @api") is False


# ── _detect_log_intent ───────────────────────────────────────────────────────

def test_detect_intent_tail_for_last_lines():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("search and show last lines of @application log") == "tail"


def test_detect_intent_tail_for_show():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("show @api log") == "tail"


def test_detect_intent_search_for_error():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("search @api log for errors") == "search"


def test_detect_intent_search_for_exception():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("see if there are exceptions in @nginx") == "search"


def test_detect_intent_default_tail():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("@api log") == "tail"


def test_detect_intent_warn_filter():
    from monix.cli import _detect_log_intent
    assert _detect_log_intent("show only warn logs for @application") == "search"


# ── _extract_lines_count ──────────────────────────────────────────────────────

def test_extract_lines_last_N_lines():
    from monix.cli import _extract_lines_count
    assert _extract_lines_count("show last 100 lines") == 100


def test_extract_lines_tail_N():
    from monix.cli import _extract_lines_count
    assert _extract_lines_count("tail 50 lines") == 50


def test_extract_lines_default():
    from monix.cli import _extract_lines_count
    assert _extract_lines_count("check errors") == 80


def test_extract_lines_N_lines_without_last():
    from monix.cli import _extract_lines_count
    assert _extract_lines_count("output 200 lines") == 200


# ── _log_search_natural (integration) ────────────────────────────────────────

def test_log_search_natural_alias_not_found(tmp_path, monkeypatch):
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)

    from monix.cli import _log_search_natural
    result = _log_search_natural("ghost", "check errors in @ghost")
    assert "not registered" in result


def test_log_search_natural_tail_intent(tmp_path, monkeypatch):
    """'show last lines' -> tail_log, not error search."""
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)
    reg_file.parent.mkdir(parents=True)
    log_file = tmp_path / "app.log"
    log_file.write_text("INFO: all good\n")
    reg_file.write_text(json.dumps([{"alias": "application", "type": "app", "path": str(log_file), "container": None}]))

    with patch("monix.tools.logs.app.subprocess.check_output", return_value="INFO: all good"):
        from monix.cli import _log_search_natural
        result = _log_search_natural("application", "search and show last lines of @application log")
    # Should render as a plain log view, not error-search result
    assert "Error/Warn" not in result
    assert "Log:" in result


def test_log_search_natural_all_lines_keyword(tmp_path, monkeypatch):
    """'all lines' should scan all lines (999999), not just default 500."""
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)
    reg_file.parent.mkdir(parents=True)
    log_file = tmp_path / "app.log"
    log_file.write_text("WARN: old warning\n" * 600 + "INFO: ok\n")
    reg_file.write_text(json.dumps([{"alias": "application", "type": "app", "path": str(log_file), "container": None}]))

    captured = {}

    def fake_check_output(cmd, **kwargs):
        captured["lines_arg"] = int(cmd[cmd.index("-n") + 1])
        return "WARN: old warning\n" * 5

    with patch("monix.tools.logs.app.subprocess.check_output", side_effect=fake_check_output):
        from monix.cli import _log_search_natural
        _log_search_natural("application", "show WARN logs from all lines of @application.")

    assert captured["lines_arg"] == 999999


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
        result = _log_search_natural("api", "search @api log for errors")
    assert "Error/Warn" in result
    assert "crash" in result
