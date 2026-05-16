from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path.home() / ".monix" / "notify_config.json"


def load_notify_config() -> dict:
    """Return persisted notify config. Returns {} if not set or unreadable."""
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_notify_config(data: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def set_notify_field(key: str, value) -> None:
    cfg = load_notify_config()
    if value is None:
        cfg.pop(key, None)
    else:
        cfg[key] = value
    save_notify_config(cfg)


def reset_notify_config() -> None:
    save_notify_config({})
