from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LogType = Literal["app", "nginx", "docker"]

_REGISTRY_DIR = Path.home() / ".monix"
_REGISTRY_FILE = _REGISTRY_DIR / "log_registry.json"


@dataclass
class LogEntry:
    alias: str
    type: LogType
    path: str | None = None
    container: str | None = None


def _load_raw() -> list[dict]:
    if not _REGISTRY_FILE.exists():
        return []
    try:
        data = json.loads(_REGISTRY_FILE.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_raw(entries: list[dict]) -> None:
    _REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    _REGISTRY_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2))


def load() -> list[LogEntry]:
    return [
        LogEntry(
            alias=e["alias"],
            type=e.get("type", "app"),
            path=e.get("path"),
            container=e.get("container"),
        )
        for e in _load_raw()
    ]


def add(
    alias: str,
    log_type: LogType,
    path: str | None = None,
    container: str | None = None,
) -> tuple[LogEntry, bool]:
    """Add or update a log entry. Returns (entry, is_new)."""
    entries = _load_raw()
    existing = next((e for e in entries if e["alias"] == alias), None)
    entry_dict: dict = {"alias": alias, "type": log_type, "path": path, "container": container}
    if existing is not None:
        existing.update(entry_dict)
        is_new = False
    else:
        entries.append(entry_dict)
        is_new = True
    _save_raw(entries)
    return LogEntry(**entry_dict), is_new


def remove(alias: str) -> bool:
    entries = _load_raw()
    filtered = [e for e in entries if e["alias"] != alias]
    if len(filtered) == len(entries):
        return False
    _save_raw(filtered)
    return True


def get(alias: str) -> LogEntry | None:
    for e in _load_raw():
        if e["alias"] == alias:
            return LogEntry(
                alias=e["alias"],
                type=e.get("type", "app"),
                path=e.get("path"),
                container=e.get("container"),
            )
    return None


def aliases() -> list[str]:
    return [e["alias"] for e in _load_raw()]
