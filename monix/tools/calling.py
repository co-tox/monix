from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from monix.tools.logs import search_log, tail_log
from monix.tools.logs.docker import search_container, tail_container
from monix.tools.logs.nginx import tail_nginx_access
from monix.tools.services import service_status

_MAX_RESULT_CHARS = 6000  # truncate large results to avoid token overload


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""  # used by Anthropic tool_use_id


# Gemini function_declarations format (also used as source for Anthropic)
TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "tail_log",
        "description": (
            "Read the last N lines from a log file. "
            "Use when the user asks to show logs, view recent entries, or tail a file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the log file (e.g. /var/log/syslog)",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to return (default 80)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_log",
        "description": (
            "Search a log file for errors, warnings, or a regex pattern. "
            "Use when the user asks to find errors, check for issues, or filter log lines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the log file",
                },
                "pattern": {
                    "type": "string",
                    "description": "Case-insensitive regex pattern. Omit to return all error/warn lines.",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to scan from the end of the file (default 500)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "tail_nginx_access",
        "description": (
            "Read an nginx access log and return lines with an HTTP status summary "
            "(status distribution, top paths, top client IPs, error lines)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to nginx access log (typically /var/log/nginx/access.log)",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to read (default 200)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "tail_container",
        "description": "Read the last N lines from a Docker container's logs.",
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Docker container name or ID",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to return (default 80)",
                },
            },
            "required": ["container"],
        },
    },
    {
        "name": "search_container",
        "description": (
            "Search Docker container logs for errors or a specific pattern. "
            "Use when the user asks to check a container for errors or filter its logs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Docker container name or ID",
                },
                "pattern": {
                    "type": "string",
                    "description": "Case-insensitive regex pattern. Omit to return error/warn lines only.",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to scan (default 500)",
                },
            },
            "required": ["container"],
        },
    },
    {
        "name": "service_status",
        "description": (
            "Check the systemd service status (active / inactive / failed). "
            "Use when the user asks about a service's health or running state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Service name (e.g. nginx, postgresql, redis)",
                },
            },
            "required": ["name"],
        },
    },
]

# Anthropic tools format (input_schema instead of parameters)
ANTHROPIC_TOOLS: list[dict] = [
    {
        "name": d["name"],
        "description": d["description"],
        "input_schema": d["parameters"],
    }
    for d in TOOL_DECLARATIONS
]

_HANDLERS: dict[str, Any] = {
    "tail_log": tail_log,
    "search_log": search_log,
    "tail_nginx_access": tail_nginx_access,
    "tail_container": tail_container,
    "search_container": search_container,
    "service_status": service_status,
}


def call_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool by name and return a JSON-serialised result string.

    Truncates large results to avoid token overload. Never raises — errors are
    returned as {"error": "..."} JSON so the LLM can see and handle them.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = handler(**args)
        serialized = json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
    if len(serialized) > _MAX_RESULT_CHARS:
        serialized = serialized[:_MAX_RESULT_CHARS] + '... [truncated]'
    return serialized
