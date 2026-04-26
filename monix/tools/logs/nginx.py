from __future__ import annotations

import re
from collections import Counter

from monix.tools.logs.app import tail_log

_ACCESS_RE = re.compile(
    r'(?P<ip>[\d.a-fA-F:]+) - \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) [^"]+" (?P<status>\d{3}) (?P<bytes>[\d-]+)'
)
_ERROR_LINE_RE = re.compile(
    r'^(?P<time>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) \[(?P<level>\w+)\] \d+#\d+: (?P<message>.+)$'
)
_NGINX_ERROR_LEVELS = {"error", "crit", "alert", "emerg"}
# Used for fallback string-based detection on unparseable lines
_NGINX_ERROR_TAGS = {"[error]", "[crit]", "[alert]", "[emerg]"}


def parse_access_line(line: str) -> dict | None:
    """Parse a single Combined Log Format access log line.

    Returns a dict with ip, time, method, path, status (int), bytes (int),
    or None if the line does not match the expected format.
    bytes is 0 when nginx logs '-' (unknown body size).
    """
    m = _ACCESS_RE.match(line)
    if not m:
        return None
    raw_bytes = m.group("bytes")
    return {
        "ip": m.group("ip"),
        "time": m.group("time"),
        "method": m.group("method"),
        "path": m.group("path"),
        "status": int(m.group("status")),
        "bytes": 0 if raw_bytes == "-" else int(raw_bytes),
    }


def summarize_access_log(lines: list[str]) -> dict:
    """Aggregate statistics from a list of nginx access log lines.

    Returns:
        total        — number of successfully parsed lines
        status_dist  — {status_code: count}
        top_paths    — top 10 paths by request count [(path, count), ...]
        top_ips      — top 10 client IPs by request count [(ip, count), ...]
        error_lines  — raw lines with HTTP status >= 400
    """
    status_counter: Counter[int] = Counter()
    path_counter: Counter[str] = Counter()
    ip_counter: Counter[str] = Counter()
    error_lines: list[str] = []

    for line in lines:
        parsed = parse_access_line(line)
        if parsed is None:
            continue
        status_counter[parsed["status"]] += 1
        path_counter[parsed["path"]] += 1
        ip_counter[parsed["ip"]] += 1
        if parsed["status"] >= 400:
            error_lines.append(line)

    return {
        "total": sum(status_counter.values()),
        "status_dist": dict(status_counter),
        "top_paths": path_counter.most_common(10),
        "top_ips": ip_counter.most_common(10),
        "error_lines": error_lines,
    }


def tail_nginx_access(path: str, lines: int = 200) -> dict:
    """Tail an nginx access log and return lines with a parsed summary.

    Extends the tail_log() result dict with a 'summary' key.
    If the file cannot be read, summary is {}.
    """
    result = tail_log(path, lines)
    if result["status"] != "ok":
        result["summary"] = {}
        return result
    result["summary"] = summarize_access_log(result["lines"])
    return result


def parse_error_line(line: str) -> dict | None:
    """Parse a single nginx error log line.

    Returns a dict with time, level, message, or None if the line does not
    match the expected format. The message includes the *CID prefix if present.
    """
    m = _ERROR_LINE_RE.match(line)
    if not m:
        return None
    return {
        "time": m.group("time"),
        "level": m.group("level"),
        "message": m.group("message"),
    }


def filter_nginx_errors(lines: list[str]) -> list[str]:
    """Return only lines with error/crit/alert/emerg severity.

    For lines that cannot be parsed by parse_error_line, falls back to
    substring matching on the level tag (e.g. '[error]').
    """
    result = []
    for line in lines:
        parsed = parse_error_line(line)
        if parsed is not None:
            if parsed["level"] in _NGINX_ERROR_LEVELS:
                result.append(line)
        else:
            if any(tag in line for tag in _NGINX_ERROR_TAGS):
                result.append(line)
    return result
