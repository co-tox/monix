from __future__ import annotations

import re
import select as _select
import subprocess
from typing import Iterator

from monix.tools.logs._types import SearchMatch, SearchResult, TailResult
from monix.tools.logs.app import DEFAULT_SEARCH_LINES, classify_line

DEFAULT_CONTAINER_TAIL: int = 80
DEFAULT_CONTAINER_FOLLOW_INITIAL: int = 20
_FOLLOW_CONNECT_TIMEOUT: float = 10.0


def _pipe_ready(stream, timeout: float) -> bool:
    """Return True if stream has data within timeout seconds, or if the check cannot be performed."""
    try:
        ready, _, _ = _select.select([stream], [], [], timeout)
        return bool(ready)
    except (AttributeError, TypeError, ValueError, OSError):
        return True  # assume ready (e.g. mock objects in tests that lack a real fd)


def tail_container(container: str, lines: int = DEFAULT_CONTAINER_TAIL) -> TailResult:
    """Fetch the last N lines from a Docker container's log. lines=0 → all."""
    if lines < 0:
        raise ValueError(f"lines must be >= 0, got {lines}")
    tail_arg = "all" if lines == 0 else str(lines)
    try:
        output = subprocess.check_output(
            ["docker", "logs", "--tail", tail_arg, container],
            text=True,
            timeout=30,
            stderr=subprocess.STDOUT,
        )
        return {"path": f"docker://{container}", "status": "ok", "lines": output.splitlines()}
    except FileNotFoundError:
        return {"path": f"docker://{container}", "status": "error", "lines": ["docker command not found"]}
    except subprocess.TimeoutExpired:
        return {"path": f"docker://{container}", "status": "error", "lines": ["timeout"]}
    except subprocess.CalledProcessError as exc:
        lines_out = (exc.output or "").splitlines()
        return {"path": f"docker://{container}", "status": "error", "lines": lines_out or [str(exc)]}
    except OSError as exc:
        return {"path": f"docker://{container}", "status": "error", "lines": [str(exc)]}


def follow_container(container: str, initial_lines: int = DEFAULT_CONTAINER_FOLLOW_INITIAL) -> Iterator[str | None]:
    """Yield container log lines in real-time.

    Raises TimeoutError if docker logs -f produces no output within
    _FOLLOW_CONNECT_TIMEOUT seconds. Yields None once when the container
    stops. Caller handles KeyboardInterrupt.
    """
    proc = subprocess.Popen(
        ["docker", "logs", "--tail", str(initial_lines), "-f", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if not proc.stdout:
        proc.terminate()
        raise RuntimeError("Failed to open stdout pipe for docker logs -f")
    if not _pipe_ready(proc.stdout, _FOLLOW_CONNECT_TIMEOUT):
        proc.terminate()
        proc.wait()
        raise TimeoutError(
            f"docker logs -f produced no output within {_FOLLOW_CONNECT_TIMEOUT:.0f}s "
            f"for container '{container}'"
        )
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
        yield None  # EOF sentinel: container stopped
    finally:
        proc.terminate()
        proc.wait()


def list_containers() -> list[dict]:
    """Return a list of running Docker containers with name, status, image."""
    try:
        output = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
            text=True,
            timeout=5,
        )
        result = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                result.append({"name": parts[0], "status": parts[1], "image": parts[2]})
        return result
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return []


def search_container(
    container: str,
    pattern: str | None = None,
    lines: int = 0,
) -> SearchResult:
    """Search container logs for errors/patterns.

    lines=0 (default) → entire log.
    pattern=None  → returns only error/warn lines.
    pattern=<str> → returns lines matching the pattern (case-insensitive regex).
    If pattern is an invalid regex, falls back to literal match.
    """
    if lines < 0:
        raise ValueError(f"lines must be >= 0, got {lines}")

    tail_result = tail_container(container, lines)
    if tail_result["status"] != "ok":
        return {
            "path": tail_result["path"],
            "status": tail_result["status"],
            "query": pattern,
            "total_scanned": 0,
            "matches": [],
        }

    all_lines = tail_result["lines"]
    warning: str | None = None

    if pattern is not None:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            compiled = re.compile(re.escape(pattern), re.IGNORECASE)
            warning = f"Invalid regex '{pattern}', searching as literal string"
        matches: list[SearchMatch] = [
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
        "path": tail_result["path"],
        "status": "ok",
        "query": pattern,
        "total_scanned": len(all_lines),
        "matches": matches,
    }
    if warning:
        result["warning"] = warning
    return result
