from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from monix.tools.logs import search_log, tail_log
from monix.tools.logs.docker import list_containers, search_container, tail_container
from monix.tools.logs.nginx import tail_nginx_access
from monix.tools.services import service_status
from monix.tools.system import collect_snapshot, cpu_usage_percent, disk_info, memory_info, top_processes

_MAX_RESULT_CHARS = 6000  # truncate large results to avoid token overload


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""  # used by Anthropic tool_use_id


# Gemini function_declarations format (also used as source for Anthropic)
TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "collect_snapshot",
        "description": (
            "Collect a read-only server health snapshot including host, OS, uptime, load average, "
            "CPU, memory, disks, top processes, and alerts. Use this first for broad health checks."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "cpu_usage_percent",
        "description": "Return the current overall CPU usage percentage.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "memory_info",
        "description": "Return memory totals, used bytes, available bytes, and usage percentage.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "disk_info",
        "description": "Return disk usage information for one or more filesystem paths.",
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filesystem paths to inspect. Defaults to ['/'].",
                },
            },
            "required": [],
        },
    },
    {
        "name": "top_processes",
        "description": "Return the top N processes sorted by CPU usage.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of processes to return. Defaults to 10.",
                    "minimum": 1,
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_containers",
        "description": (
            "List running Docker containers with their name, status, and image. "
            "Use this first when the user asks about Docker containers but hasn't specified a container name."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
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
                    "minimum": 1,
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
                    "minimum": 1,
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
                    "minimum": 1,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "tail_container",
        "description": (
            "Read the last N lines from a Docker container's logs. "
            "Use when the user asks to show or tail a specific container's logs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Docker container name or ID (use list_containers to discover names)",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to return (default 80)",
                    "minimum": 1,
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
                    "description": "Docker container name or ID (use list_containers to discover names)",
                },
                "pattern": {
                    "type": "string",
                    "description": "Case-insensitive regex pattern. Omit to return error/warn lines only.",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to scan (default 500)",
                    "minimum": 1,
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
    "collect_snapshot": collect_snapshot,
    "cpu_usage_percent": cpu_usage_percent,
    "memory_info": memory_info,
    "disk_info": disk_info,
    "top_processes": top_processes,
    "list_containers": list_containers,
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
