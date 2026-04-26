from unittest.mock import patch

import pytest

from monix.tools.logs.nginx import (
    filter_nginx_errors,
    parse_access_line,
    parse_error_line,
    summarize_access_log,
    tail_nginx_access,
)
from monix.render import render_docker_containers, render_nginx_summary

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_ACCESS_LINE = (
    '203.0.113.5 - frank [26/Apr/2026:12:00:00 +0900] '
    '"GET /api/v1/users HTTP/1.1" 200 1234 "-" "Mozilla/5.0"'
)
SAMPLE_ACCESS_LINE_404 = (
    '198.51.100.22 - - [26/Apr/2026:12:01:00 +0900] '
    '"GET /missing HTTP/1.1" 404 512 "-" "curl/7.68.0"'
)
SAMPLE_ACCESS_LINE_500 = (
    '10.0.0.1 - - [26/Apr/2026:12:02:00 +0900] '
    '"POST /api/v1/data HTTP/1.1" 500 0 "-" "-"'
)
SAMPLE_ACCESS_LINE_BYTES_DASH = (
    '203.0.113.5 - - [26/Apr/2026:12:03:00 +0900] '
    '"HEAD /health HTTP/1.1" 200 - "-" "-"'
)
SAMPLE_ERROR_LINE = (
    '2026/04/26 12:00:00 [error] 1234#1234: *1 '
    'connect() failed (111: Connection refused), client: 203.0.113.5'
)
SAMPLE_CRIT_LINE = (
    '2026/04/26 12:01:00 [crit] 1234#1234: *2 SSL_read() failed'
)
SAMPLE_ALERT_LINE = (
    '2026/04/26 12:02:00 [alert] 1234#1234: *3 worker process exited'
)
SAMPLE_WARN_LINE = (
    '2026/04/26 12:03:00 [warn] 1234#1234: *4 upstream response buffered'
)


# ---------------------------------------------------------------------------
# parse_access_line
# ---------------------------------------------------------------------------

def test_parse_access_line_ok():
    result = parse_access_line(SAMPLE_ACCESS_LINE)
    assert result is not None
    assert result["ip"] == "203.0.113.5"
    assert result["method"] == "GET"
    assert result["path"] == "/api/v1/users"
    assert result["status"] == 200
    assert result["bytes"] == 1234


def test_parse_access_line_404():
    result = parse_access_line(SAMPLE_ACCESS_LINE_404)
    assert result is not None
    assert result["status"] == 404
    assert result["ip"] == "198.51.100.22"


def test_parse_access_line_types_are_int():
    result = parse_access_line(SAMPLE_ACCESS_LINE)
    assert isinstance(result["status"], int)
    assert isinstance(result["bytes"], int)


def test_parse_access_line_bytes_dash_returns_zero():
    result = parse_access_line(SAMPLE_ACCESS_LINE_BYTES_DASH)
    assert result is not None
    assert result["bytes"] == 0


def test_parse_access_line_invalid_returns_none():
    assert parse_access_line("not a log line") is None
    assert parse_access_line("") is None
    assert parse_access_line("127.0.0.1 incomplete line") is None


# ---------------------------------------------------------------------------
# summarize_access_log
# ---------------------------------------------------------------------------

def test_summarize_status_dist():
    lines = [SAMPLE_ACCESS_LINE, SAMPLE_ACCESS_LINE_404, SAMPLE_ACCESS_LINE_500]
    result = summarize_access_log(lines)
    assert result["status_dist"][200] == 1
    assert result["status_dist"][404] == 1
    assert result["status_dist"][500] == 1
    assert result["total"] == 3


def test_summarize_top_paths():
    lines = [SAMPLE_ACCESS_LINE] * 5 + [SAMPLE_ACCESS_LINE_404]
    result = summarize_access_log(lines)
    paths = dict(result["top_paths"])
    assert paths["/api/v1/users"] == 5
    assert paths["/missing"] == 1


def test_summarize_top_paths_sorted_by_count():
    lines = [SAMPLE_ACCESS_LINE] * 3 + [SAMPLE_ACCESS_LINE_404] * 7
    result = summarize_access_log(lines)
    counts = [count for _, count in result["top_paths"]]
    assert counts == sorted(counts, reverse=True)


def test_summarize_error_lines():
    lines = [SAMPLE_ACCESS_LINE, SAMPLE_ACCESS_LINE_404, SAMPLE_ACCESS_LINE_500]
    result = summarize_access_log(lines)
    assert len(result["error_lines"]) == 2
    assert SAMPLE_ACCESS_LINE_404 in result["error_lines"]
    assert SAMPLE_ACCESS_LINE_500 in result["error_lines"]
    assert SAMPLE_ACCESS_LINE not in result["error_lines"]


def test_summarize_empty_input():
    result = summarize_access_log([])
    assert result["total"] == 0
    assert result["status_dist"] == {}
    assert result["top_paths"] == []
    assert result["top_ips"] == []
    assert result["error_lines"] == []


def test_summarize_skips_unparseable_lines():
    lines = ["not a log line", "also garbage", SAMPLE_ACCESS_LINE]
    result = summarize_access_log(lines)
    assert result["total"] == 1


# ---------------------------------------------------------------------------
# tail_nginx_access
# ---------------------------------------------------------------------------

def test_tail_nginx_access_ok():
    fake_tail = {
        "path": "/var/log/nginx/access.log",
        "status": "ok",
        "lines": [SAMPLE_ACCESS_LINE, SAMPLE_ACCESS_LINE_404],
    }
    with patch("monix.tools.logs.nginx.tail_log", return_value=fake_tail):
        result = tail_nginx_access("/var/log/nginx/access.log")
    assert result["status"] == "ok"
    assert "summary" in result
    assert result["summary"]["total"] == 2


def test_tail_nginx_access_missing_file():
    fake_tail = {"path": "/bad/path", "status": "missing", "lines": []}
    with patch("monix.tools.logs.nginx.tail_log", return_value=fake_tail):
        result = tail_nginx_access("/bad/path")
    assert result["status"] == "missing"
    assert result["summary"] == {}


def test_tail_nginx_access_passes_lines_param():
    fake_tail = {"path": "/p", "status": "ok", "lines": [SAMPLE_ACCESS_LINE]}
    with patch("monix.tools.logs.nginx.tail_log", return_value=fake_tail) as mock_tail:
        tail_nginx_access("/p", lines=500)
    mock_tail.assert_called_once_with("/p", 500)


# ---------------------------------------------------------------------------
# parse_error_line
# ---------------------------------------------------------------------------

def test_parse_error_line_ok():
    result = parse_error_line(SAMPLE_ERROR_LINE)
    assert result is not None
    assert result["level"] == "error"
    assert "2026/04/26" in result["time"]
    assert len(result["message"]) > 0


def test_parse_error_line_warn():
    result = parse_error_line(SAMPLE_WARN_LINE)
    assert result is not None
    assert result["level"] == "warn"


def test_parse_error_line_crit():
    result = parse_error_line(SAMPLE_CRIT_LINE)
    assert result is not None
    assert result["level"] == "crit"


def test_parse_error_line_invalid_returns_none():
    assert parse_error_line("not an error log line") is None
    assert parse_error_line("") is None
    assert parse_error_line("2026/04/26 incomplete") is None


# ---------------------------------------------------------------------------
# filter_nginx_errors
# ---------------------------------------------------------------------------

def test_filter_keeps_error_level():
    result = filter_nginx_errors([SAMPLE_ERROR_LINE, SAMPLE_WARN_LINE])
    assert len(result) == 1
    assert SAMPLE_ERROR_LINE in result


def test_filter_keeps_crit_and_alert():
    lines = [SAMPLE_CRIT_LINE, SAMPLE_ALERT_LINE, SAMPLE_WARN_LINE]
    result = filter_nginx_errors(lines)
    assert len(result) == 2
    assert SAMPLE_CRIT_LINE in result
    assert SAMPLE_ALERT_LINE in result


def test_filter_excludes_warn():
    result = filter_nginx_errors([SAMPLE_WARN_LINE])
    assert result == []


def test_filter_empty_input():
    assert filter_nginx_errors([]) == []


def test_filter_no_matches():
    lines = [SAMPLE_WARN_LINE, "INFO: all good", "DEBUG: nothing"]
    assert filter_nginx_errors(lines) == []


def test_filter_fallback_string_match():
    # Unparseable line that still contains [error] tag
    unparseable = "some garbled line with [error] in it"
    result = filter_nginx_errors([unparseable])
    assert unparseable in result


# ---------------------------------------------------------------------------
# render_nginx_summary
# ---------------------------------------------------------------------------

_FULL_SUMMARY = {
    "path": "/var/log/nginx/access.log",
    "status": "ok",
    "lines": [],
    "summary": {
        "total": 100,
        "status_dist": {200: 90, 404: 8, 500: 2},
        "top_paths": [("/index.html", 50), ("/api", 40), ("/health", 10)],
        "top_ips": [("1.2.3.4", 60), ("5.6.7.8", 40)],
        "error_lines": ["err line 1", "err line 2"],
    },
}


def test_render_nginx_summary_contains_total():
    rendered = render_nginx_summary(_FULL_SUMMARY)
    assert "100" in rendered


def test_render_nginx_summary_contains_status_codes():
    rendered = render_nginx_summary(_FULL_SUMMARY)
    assert "200" in rendered
    assert "404" in rendered
    assert "500" in rendered


def test_render_nginx_summary_contains_top_paths():
    rendered = render_nginx_summary(_FULL_SUMMARY)
    assert "/index.html" in rendered
    assert "/api" in rendered


def test_render_nginx_summary_contains_top_ips():
    rendered = render_nginx_summary(_FULL_SUMMARY)
    assert "1.2.3.4" in rendered


def test_render_nginx_summary_error_status_delegates():
    result = {"path": "/bad/path", "status": "missing", "lines": [], "summary": {}}
    rendered = render_nginx_summary(result)
    assert "missing" in rendered
def test_render_nginx_summary_empty_summary_message():
    result = {
        "path": "/var/log/nginx/access.log",
        "status": "ok",
        "lines": [],
        "summary": {
            "total": 0,
            "status_dist": {},
            "top_paths": [],
            "top_ips": [],
            "error_lines": [],
        },
    }
    rendered = render_nginx_summary(result)
    assert "파싱된 라인 없음" in rendered


# ---------------------------------------------------------------------------
# render_docker_containers
# ---------------------------------------------------------------------------

_CONTAINERS = [
    {"name": "web", "status": "Up 2 hours", "image": "nginx:latest"},
    {"name": "db", "status": "Up 1 day", "image": "postgres:15"},
]


def test_render_docker_containers_table_content():
    rendered = render_docker_containers(_CONTAINERS)
    assert "web" in rendered


def test_render_docker_containers_empty():
    rendered = render_docker_containers([])
    assert "실행 중인 컨테이너 없음" in rendered


def test_render_docker_containers_shows_registration_hints():
    rendered = render_docker_containers(_CONTAINERS)
    assert "/docker add" in rendered
    assert "web" in rendered


def test_render_docker_containers_empty_message():
    rendered = render_docker_containers([])
    assert "실행 중인 컨테이너 없음" in rendered


def test_render_docker_containers_hint_per_container():
    containers = [{"name": "myapp", "status": "Up", "image": "myapp:1.0"}]
    rendered = render_docker_containers(containers)
    assert "myapp" in rendered
    assert "alias" in rendered
