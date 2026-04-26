# monix/tools/logs — Log Monitoring Module

## Overview

A collection of tools to view and stream server application logs, Nginx logs, and Docker container logs.
All features adhere to the **Read-only** principle and use only the Python standard library.

---

## Directory Structure

```
monix/tools/logs/
├── README.md          # This document
├── __init__.py        # Public API (Package entry point)
├── _types.py          # Shared type definitions (TypedDict)
├── app.py             # File-based log view/streaming (supports compressed files)
├── registry.py        # Log registration persistence (with caching and validation)
├── nginx.py           # Nginx log parsing and aggregation
└── docker/            # Docker container log modularization
    ├── __init__.py
    └── containers.py  # Container log wrapping and searching
```

---

## Module Description

### `app.py` — Core App Log Functions

| Function | Signature | Description |
|------|----------|------|
| `tail_log` | `(path, lines=80) → TailResult` | Read last N lines of a file (supports compressed files) |
| `search_log` | `(path, pattern=None, lines=500) → SearchResult` | Keyword search or error filter |
| `filter_errors` | `(lines) → list[str]` | Filter lines matching ERROR/WARN patterns |
| `classify_line` | `(line) → Severity` | Classify severity of a single line (`error`, `warn`, `normal`) |
| `follow_log` | `(path, initial_lines=20) → Iterator[str\|None]` | `tail -f` real-time streaming generator |

**Key Features**
- **Compressed File Support**: Automatically detects and decompresses `.gz`, `.bz2`, `.xz`, `.lzma` files.
- **Enhanced Search**: Automatically falls back to literal search if a regex pattern is invalid.
- **Streaming**: `follow_log` yields `None` if the file is rotated or deleted, causing `tail` to exit.

---

### `nginx.py` — Nginx Log Analysis

Parses Nginx Access/Error logs and extracts statistics (based on Combined Log Format).

| Function | Signature | Description |
|------|----------|------|
| `tail_nginx_access` | `(path, lines=200) → NginxTailResult` | Tail Access log with aggregation summary |
| `summarize_access_log` | `(lines) → NginxSummary` | Status code distribution, Top Path/IP aggregation |
| `parse_access_line` | `(line) → dict \| None` | Parse a single Access log line |
| `filter_nginx_errors` | `(lines) → list[str]` | Filter Error logs by severity (error and above) |
| `parse_error_line` | `(line) → dict \| None` | Parse a single Error log line |

---

### `registry.py` — Log Registration Management

Registration info is persisted in `~/.monix/log_registry.json`. Module-level caching is used for performance.

**Public Functions**

| Function | Signature | Description |
|------|----------|------|
| `load` | `() → list[LogEntry]` | Load all entries (uses cache) |
| `add` | `(alias, type, path, container) → (LogEntry, is_new)` | Register or update with validation |
| `remove` | `(alias) → bool` | Unregister an entry |
| `get` | `(alias) → LogEntry \| None` | Get a single entry |
| `aliases` | `() → list[str]` | List of registered alias names |

---

### `docker/` — Docker Container Logs

Fetches logs by calling the Docker CLI. Includes container-specific search features.

| Function | Signature | Description |
|------|----------|------|
| `tail_container` | `(container, lines=80) → TailResult` | Last N lines of container logs |
| `search_container` | `(container, pattern, lines=500) → SearchResult` | Pattern search in container logs |
| `follow_container` | `(container, lines=20) → Iterator[str\|None]` | Real-time streaming (with timeout detection) |
| `list_containers` | `() → list[dict]` | List running containers (`docker ps`) |

---

## CLI Command Reference

### Registration Management

```bash
# Register app logs
/log add @api    -app    /var/log/myapp/api.log
/log add @nginx  -nginx  /var/log/nginx/access.log
/log add @web    -docker web_container

# Docker-specific shortcut
/docker add @web web_container
```

### Log Viewing and Searching

```bash
# Using registered aliases
/log @api                   # Default 80 lines
/log @api --search "pattern" # Pattern search

# Docker-specific viewing
/docker logs @web
/docker search @web "error"
```

---

## Future Plans

| Phase | Feature | File |
|-------|------|------|
| 3 | Error pattern aggregation ("15 DB timeouts in last 10 min") | `app.py` extension |
| 3 | LLM Integration — Auto error summary (`/ask` extension) | `core/assistant.py` |

For more details, see [`docs/issues/004-log-tools-improvements.md`](../../../docs/issues/004-log-tools-improvements.md).
