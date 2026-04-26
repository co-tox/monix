from __future__ import annotations

import bz2
import contextlib
import gzip
import lzma
import re
import subprocess
from pathlib import Path
from typing import IO, Generator, Iterator

from monix.tools.logs._types import SearchResult, Severity, TailResult

_ERROR_RE = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|Exception|Traceback)\b",
    re.IGNORECASE,
)
_WARN_RE = re.compile(r"\b(WARN|WARNING)\b", re.IGNORECASE)

DEFAULT_TAIL_LINES: int = 80
DEFAULT_FOLLOW_INITIAL: int = 20
DEFAULT_SEARCH_LINES: int = 500
_COMPRESSED_SUFFIXES = frozenset({".gz", ".bz2", ".bz", ".xz", ".lzma"})


@contextlib.contextmanager
def _open_compressed(path: Path) -> Generator[IO[str], None, None]:
    suffix = path.suffix.lower()
    if suffix == ".gz":
        fh: IO[str] = gzip.open(path, "rt", errors="replace")
    elif suffix in (".bz2", ".bz"):
        fh = bz2.open(path, "rt", errors="replace")
    else:  # .xz or .lzma
        fh = lzma.open(path, "rt", errors="replace")
    try:
        yield fh
    finally:
        fh.close()


def tail_log(path: str | Path, lines: int = DEFAULT_TAIL_LINES) -> TailResult:
    if lines < 1:
        raise ValueError(f"lines must be >= 1, got {lines}")
    log_path = Path(path).expanduser()
    if not log_path.exists():
        return {"path": str(log_path), "status": "missing", "lines": []}
    if not log_path.is_file():
        return {"path": str(log_path), "status": "not_file", "lines": []}
    if log_path.suffix.lower() in _COMPRESSED_SUFFIXES:
        try:
            with _open_compressed(log_path) as fh:
                all_lines = fh.read().splitlines()
            return {"path": str(log_path), "status": "ok", "lines": all_lines[-lines:]}
        except (OSError, EOFError) as exc:
            return {"path": str(log_path), "status": "error", "lines": [str(exc)]}
    try:
        output = subprocess.check_output(
            ["tail", "-n", str(lines), str(log_path)],
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        return {"path": str(log_path), "status": "error", "lines": [str(exc)]}
    return {"path": str(log_path), "status": "ok", "lines": output.splitlines()}


def filter_errors(lines: list[str]) -> list[str]:
    """Return only lines matching error or warning patterns."""
    return [line for line in lines if _ERROR_RE.search(line) or _WARN_RE.search(line)]


def classify_line(line: str) -> Severity:
    """Return 'error', 'warn', or 'normal' severity for a log line."""
    if _ERROR_RE.search(line):
        return "error"
    if _WARN_RE.search(line):
        return "warn"
    return "normal"


def search_log(
    path: str | Path,
    pattern: str | None = None,
    lines: int = 0,
) -> SearchResult:
    """Search a log file.

    lines=0 (default) → entire file.
    lines>0 → last N lines only.
    pattern=None → returns only error/warn lines.
    pattern=<str> → returns lines matching the regex (case-insensitive).
    If pattern is an invalid regex, falls back to literal match and sets
    result['warning'].
    """
    if lines < 0:
        raise ValueError(f"lines must be >= 0, got {lines}")
    log_path = Path(path).expanduser()
    if not log_path.exists():
        return {"path": str(log_path), "status": "missing", "query": pattern, "total_scanned": 0, "matches": []}
    if not log_path.is_file():
        return {"path": str(log_path), "status": "not_file", "query": pattern, "total_scanned": 0, "matches": []}

    if log_path.suffix.lower() in _COMPRESSED_SUFFIXES:
        try:
            with _open_compressed(log_path) as fh:
                raw = fh.read().splitlines()
                all_lines = raw[-lines:] if lines > 0 else raw
        except (OSError, EOFError) as exc:
            return {"path": str(log_path), "status": "error", "query": pattern, "total_scanned": 0, "matches": [str(exc)]}
    else:
        try:
            cmd = ["tail", "-n", str(lines), str(log_path)] if lines > 0 else ["cat", str(log_path)]
            output = subprocess.check_output(cmd, text=True, timeout=30)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            return {"path": str(log_path), "status": "error", "query": pattern, "total_scanned": 0, "matches": [str(exc)]}
        all_lines = output.splitlines()

    warning: str | None = None

    if pattern is not None:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            compiled = re.compile(re.escape(pattern), re.IGNORECASE)
            warning = f"Invalid regex '{pattern}', searching as literal string"
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

    result: SearchResult = {
        "path": str(log_path),
        "status": "ok",
        "query": pattern,
        "total_scanned": len(all_lines),
        "matches": matches,
    }
    if warning:
        result["warning"] = warning
    return result


def follow_log(path: str | Path, initial_lines: int = DEFAULT_FOLLOW_INITIAL) -> Iterator[str | None]:
    """Yield log lines in real-time using tail -f.

    Yields str for each line, then None once if tail -f exits unexpectedly
    (e.g. file deleted or rotated). Caller handles KeyboardInterrupt.
    """
    log_path = Path(path).expanduser()
    if log_path.suffix.lower() in _COMPRESSED_SUFFIXES:
        raise ValueError(f"follow_log() does not support compressed files: {log_path}")
    proc = subprocess.Popen(
        ["tail", "-n", str(initial_lines), "-f", str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if not proc.stdout:
        proc.terminate()
        raise RuntimeError("Failed to open stdout pipe for tail -f")
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
        yield None  # EOF sentinel: tail -f exited unexpectedly (file deleted/rotated)
    finally:
        proc.terminate()
        proc.wait()
