from __future__ import annotations

from typing import Literal, TypedDict

LogStatus = Literal["ok", "missing", "not_file", "error"]
Severity = Literal["error", "warn", "normal"]


class TailResult(TypedDict):
    path: str
    status: LogStatus
    lines: list[str]


class SearchMatch(TypedDict):
    lineno: int
    line: str
    severity: Severity


class _SearchResultBase(TypedDict):
    path: str
    status: LogStatus
    query: str | None
    total_scanned: int
    matches: list[SearchMatch]


class SearchResult(_SearchResultBase, total=False):
    """Result of search_log(). 'warning' is set only when pattern was invalid regex."""
    warning: str


class NginxSummary(TypedDict):
    total: int
    status_dist: dict[int, int]
    top_paths: list[tuple[str, int]]
    top_ips: list[tuple[str, int]]
    error_lines: list[str]


class NginxTailResult(TailResult):
    """TailResult with nginx aggregation. summary is {} when file cannot be read."""
    summary: NginxSummary | dict[str, object]
