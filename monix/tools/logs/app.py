from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterator

_ERROR_RE = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|Exception|Traceback)\b",
    re.IGNORECASE,
)
_WARN_RE = re.compile(r"\b(WARN|WARNING)\b", re.IGNORECASE)


def tail_log(path: str | Path, lines: int = 80) -> dict:
    if lines < 1:
        raise ValueError(f"lines must be >= 1, got {lines}")
    log_path = Path(path).expanduser()
    if not log_path.exists():
        return {"path": str(log_path), "status": "missing", "lines": []}
    if not log_path.is_file():
        return {"path": str(log_path), "status": "not_file", "lines": []}
    try:
        output = subprocess.check_output(
            ["tail", "-n", str(lines), str(log_path)],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"path": str(log_path), "status": "error", "lines": [str(exc)]}
    return {"path": str(log_path), "status": "ok", "lines": output.splitlines()}


def filter_errors(lines: list[str]) -> list[str]:
    """Return only lines matching error or warning patterns."""
    return [line for line in lines if _ERROR_RE.search(line) or _WARN_RE.search(line)]


def classify_line(line: str) -> str:
    """Return 'error', 'warn', or 'normal' severity for a log line."""
    if _ERROR_RE.search(line):
        return "error"
    if _WARN_RE.search(line):
        return "warn"
    return "normal"


def search_log(path: str | Path, pattern: str | None = None, lines: int = 500) -> dict:
    """Search last N lines of a log file.

    pattern=None → returns only error/warn lines.
    pattern=<str> → returns lines matching the regex (case-insensitive).
    """
    log_path = Path(path).expanduser()
    if not log_path.exists():
        return {"path": str(log_path), "status": "missing", "query": pattern, "total_scanned": 0, "matches": []}
    if not log_path.is_file():
        return {"path": str(log_path), "status": "not_file", "query": pattern, "total_scanned": 0, "matches": []}
    try:
        output = subprocess.check_output(
            ["tail", "-n", str(lines), str(log_path)],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"path": str(log_path), "status": "error", "query": pattern, "total_scanned": 0, "matches": [str(exc)]}

    all_lines = output.splitlines()

    if pattern is not None:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            compiled = re.compile(re.escape(pattern), re.IGNORECASE)
        matches = [
            {"lineno": i + 1, "line": line, "severity": classify_line(line)}
            for i, line in enumerate(all_lines)
            if compiled.search(line)
        ]
    else:
        matches = [
            {"lineno": i + 1, "line": line, "severity": classify_line(line)}
            for i, line in enumerate(all_lines)
            if classify_line(line) != "normal"
        ]

    return {
        "path": str(log_path),
        "status": "ok",
        "query": pattern,
        "total_scanned": len(all_lines),
        "matches": matches,
    }


def follow_log(path: str | Path, initial_lines: int = 20) -> Iterator[str]:
    """Yield log lines in real-time using tail -f. Caller handles KeyboardInterrupt."""
    log_path = Path(path).expanduser()
    proc = subprocess.Popen(
        ["tail", "-n", str(initial_lines), "-f", str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert proc.stdout
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.terminate()
        proc.wait()
