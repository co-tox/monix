import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from monix.tools.logs.app import classify_line, filter_errors, follow_log, tail_log


# --- tail_log ---

def test_tail_log_missing_file(tmp_path):
    result = tail_log(tmp_path / "nonexistent.log")
    assert result["status"] == "missing"
    assert result["lines"] == []


def test_tail_log_not_a_file(tmp_path):
    result = tail_log(tmp_path)
    assert result["status"] == "not_file"
    assert result["lines"] == []


def test_tail_log_ok(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("line1\nline2\nline3\n")
    with patch("monix.tools.logs.app.subprocess.check_output", return_value="line1\nline2\nline3"):
        result = tail_log(log)
    assert result["status"] == "ok"
    assert "line1" in result["lines"]


def test_tail_log_subprocess_error(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("data")
    with patch("monix.tools.logs.app.subprocess.check_output", side_effect=OSError("fail")):
        result = tail_log(log)
    assert result["status"] == "error"
    assert result["lines"] != []


def test_tail_log_path_returned(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("x")
    with patch("monix.tools.logs.app.subprocess.check_output", return_value="x"):
        result = tail_log(log)
    assert result["path"] == str(log)


# --- filter_errors ---

def test_filter_errors_keeps_error_lines():
    lines = ["INFO: ok", "ERROR: something failed", "DEBUG: boring", "FATAL: crash"]
    result = filter_errors(lines)
    assert len(result) == 2
    assert all("ERROR" in l or "FATAL" in l for l in result)


def test_filter_errors_keeps_warn_lines():
    lines = ["INFO: ok", "WARN: disk almost full", "WARNING: low memory"]
    result = filter_errors(lines)
    assert len(result) == 2


def test_filter_errors_empty_input():
    assert filter_errors([]) == []


def test_filter_errors_no_matches():
    assert filter_errors(["INFO: all good", "DEBUG: nothing"]) == []


def test_filter_errors_case_insensitive():
    assert filter_errors(["error: lowercase"]) != []
    assert filter_errors(["Traceback (most recent call last):"]) != []


# --- classify_line ---

def test_classify_line_error():
    assert classify_line("ERROR: db connection failed") == "error"


def test_classify_line_fatal():
    assert classify_line("FATAL: out of memory") == "error"


def test_classify_line_exception():
    assert classify_line("Exception: timeout") == "error"


def test_classify_line_traceback():
    assert classify_line("Traceback (most recent call last):") == "error"


def test_classify_line_warn():
    assert classify_line("WARN: disk at 80%") == "warn"


def test_classify_line_warning():
    assert classify_line("WARNING: slow query") == "warn"


def test_classify_line_normal():
    assert classify_line("INFO: request processed") == "normal"


def test_classify_line_empty():
    assert classify_line("") == "normal"


# --- follow_log ---

def test_follow_log_yields_lines(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("line1\nline2\n")

    mock_proc = MagicMock()
    mock_proc.stdout = iter(["line1\n", "line2\n"])
    with patch("monix.tools.logs.app.subprocess.Popen", return_value=mock_proc):
        lines = list(follow_log(log, initial_lines=2))
    assert lines == ["line1", "line2"]
    mock_proc.terminate.assert_called_once()


def test_follow_log_terminates_on_exhaustion(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("")

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    with patch("monix.tools.logs.app.subprocess.Popen", return_value=mock_proc):
        list(follow_log(log))
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()
