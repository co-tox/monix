from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from monix.tools.config_actions import (
    collect_set_config,
    log_add,
    notify_add_log_ignore,
    notify_set_cooldown,
    notify_set_log_cooldown,
    notify_set_log_errors,
    notify_set_log_severity,
    notify_set_metric_alert,
    notify_set_webhook,
)
from monix.tools.logs import search_log, tail_log
from monix.tools.logs.docker import list_containers, search_container, tail_container
from monix.tools.logs.nginx import tail_nginx_access
from monix.tools.services import list_services, service_status
from monix.tools.system import (
    all_processes,
    collect_snapshot,
    container_inspect,
    container_processes,
    container_stats,
    cpu_core_usage_percents,
    cpu_usage_percent,
    disk_info,
    disk_io,
    load_average,
    memory_info,
    network_io,
    swap_info,
    top_processes,
)

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
    {
        "name": "cpu_info",
        "description": (
            "Return full CPU information: overall usage percentage, load averages (1/5/15 min), "
            "and per-core usage percentages. Use when the user asks about CPU details, load, or cores."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "swap_info",
        "description": "Return swap memory usage: total, used, free bytes, and usage percentage.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "network_io",
        "description": (
            "Return per-interface network I/O rates (rx/tx bytes per second) over a sample period. "
            "Use when the user asks about network traffic, bandwidth, or interface activity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sample_seconds": {
                    "type": "number",
                    "description": "Sample duration in seconds (default 1.0).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "disk_io",
        "description": (
            "Return per-device disk I/O rates (read/write bytes per second) over a sample period. "
            "Use when the user asks about disk throughput or I/O activity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sample_seconds": {
                    "type": "number",
                    "description": "Sample duration in seconds (default 1.0).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "all_processes",
        "description": (
            "Return all running processes sorted by CPU usage with PID, CPU%, MEM%, and command. "
            "Use when the user asks to list all processes or find a specific process by name."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_services",
        "description": (
            "List all systemd services with their active state and description. "
            "Use when the user asks to show all services or list running/failed services."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "container_stats",
        "description": (
            "Return Docker container resource usage statistics: CPU%, memory, network I/O, block I/O. "
            "Optionally filter by a specific container name. "
            "Use when the user asks about Docker resource usage or container performance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Container name or ID to filter. Omit for all containers.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "container_processes",
        "description": (
            "List processes running inside a Docker container (equivalent to docker top). "
            "Use when the user asks what is running inside a specific container."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Docker container name or ID (use list_containers to discover names)",
                },
            },
            "required": ["container"],
        },
    },
    {
        "name": "container_inspect",
        "description": (
            "Inspect a Docker container: ports, mounts, environment variables, "
            "health status, and network configuration. "
            "Use when the user asks for container configuration details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Docker container name or ID",
                },
            },
            "required": ["container"],
        },
    },
    # ── Monix configuration write tools (Tier 2) ─────────────────────────────
    {
        "name": "log_add",
        "description": (
            "Register a log source (app/nginx/docker) with an alias for monitoring. "
            "Use when the user asks to add or register a log file or Docker container."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "alias": {
                    "type": "string",
                    "description": "Short alias name without @. e.g. 'api', 'nginx'",
                },
                "log_type": {
                    "type": "string",
                    "enum": ["app", "nginx", "docker"],
                    "description": "Log source type",
                },
                "path": {
                    "type": "string",
                    "description": "Absolute file path (required for app/nginx types)",
                },
                "container": {
                    "type": "string",
                    "description": "Docker container name (required for docker type)",
                },
            },
            "required": ["alias", "log_type"],
        },
    },
    {
        "name": "notify_set_webhook",
        "description": (
            "Set or clear a Discord or Slack webhook URL for alert notifications. "
            "Use when the user asks to configure a webhook URL."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["discord", "slack"],
                    "description": "Webhook platform",
                },
                "url": {
                    "type": "string",
                    "description": "Webhook URL. Omit or null to clear the URL.",
                },
            },
            "required": ["platform"],
        },
    },
    {
        "name": "notify_set_metric_alert",
        "description": "Enable or disable CPU, memory, or disk metric threshold alert notifications.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["cpu", "memory", "disk"],
                    "description": "Metric type",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "true to enable, false to disable",
                },
            },
            "required": ["metric", "enabled"],
        },
    },
    {
        "name": "notify_set_cooldown",
        "description": "Set the cooldown period (seconds) between repeated metric alert notifications.",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "Cooldown in seconds (default 3600)",
                    "minimum": 0,
                },
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "notify_set_log_errors",
        "description": "Enable or disable log error webhook alert notifications.",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "true to enable, false to disable",
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "notify_set_log_severity",
        "description": "Set the minimum log severity level for alert notifications: 'error' or 'warn'.",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["error", "warn"],
                    "description": "Minimum severity level",
                },
            },
            "required": ["severity"],
        },
    },
    {
        "name": "notify_set_log_cooldown",
        "description": "Set the cooldown period (seconds) between repeated log error alert notifications.",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "Log alert cooldown in seconds (default 300)",
                    "minimum": 0,
                },
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "notify_add_log_ignore",
        "description": (
            "Add a pattern to the log ignore list. "
            "Log lines containing this pattern will not trigger webhook alerts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "String pattern to ignore (case-insensitive substring match)",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "collect_set_config",
        "description": (
            "Configure the metrics history collector. "
            "Use when the user asks to set up or update the data collection schedule and storage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "interval": {
                    "type": "string",
                    "description": "Collection interval with unit: e.g. '1h', '30m', '1d'",
                },
                "retention": {
                    "type": "string",
                    "description": "Data retention period with unit: e.g. '30d', '7d', '24h'",
                },
                "folder": {
                    "type": "string",
                    "description": "Absolute path to the storage folder",
                },
            },
            "required": ["interval", "retention", "folder"],
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

def _cpu_info() -> dict:
    return {
        "cpu_percent": cpu_usage_percent(),
        "load_average": load_average(),
        "core_percents": cpu_core_usage_percents(),
    }


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
    "cpu_info": _cpu_info,
    "swap_info": swap_info,
    "network_io": network_io,
    "disk_io": disk_io,
    "all_processes": all_processes,
    "list_services": list_services,
    "container_stats": container_stats,
    "container_processes": container_processes,
    "container_inspect": container_inspect,
    "log_add": log_add,
    "notify_set_webhook": notify_set_webhook,
    "notify_set_metric_alert": notify_set_metric_alert,
    "notify_set_cooldown": notify_set_cooldown,
    "notify_set_log_errors": notify_set_log_errors,
    "notify_set_log_severity": notify_set_log_severity,
    "notify_set_log_cooldown": notify_set_log_cooldown,
    "notify_add_log_ignore": notify_add_log_ignore,
    "collect_set_config": collect_set_config,
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
