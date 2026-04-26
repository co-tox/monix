from __future__ import annotations

from monix.tools.logs._types import (
    LogStatus,
    NginxSummary,
    NginxTailResult,
    SearchMatch,
    SearchResult,
    Severity,
    TailResult,
)
from monix.tools.logs.app import classify_line, filter_errors, follow_log, search_log, tail_log
from monix.tools.logs.docker import follow_container, list_containers, search_container, tail_container
from monix.tools.logs.nginx import (
    filter_nginx_errors,
    parse_access_line,
    parse_error_line,
    summarize_access_log,
    tail_nginx_access,
)
from monix.tools.logs import registry

__all__ = [
    # types
    "LogStatus",
    "Severity",
    "TailResult",
    "SearchMatch",
    "SearchResult",
    "NginxSummary",
    "NginxTailResult",
    # app
    "tail_log",
    "search_log",
    "filter_errors",
    "classify_line",
    "follow_log",
    # docker
    "tail_container",
    "follow_container",
    "list_containers",
    "search_container",
    # nginx
    "parse_access_line",
    "summarize_access_log",
    "tail_nginx_access",
    "parse_error_line",
    "filter_nginx_errors",
    # registry
    "registry",
]
