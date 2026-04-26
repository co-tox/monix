from __future__ import annotations

import json
import os
import stat
from pathlib import Path

_CONFIG_DIR = Path.home() / ".monix"
_CONFIG_FILE = _CONFIG_DIR / "config.json"


def load_api_key() -> str | None:
    if not _CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        return data.get("gemini_api_key") or None
    except (json.JSONDecodeError, OSError):
        return None


def save_api_key(key: str) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data["gemini_api_key"] = key
    _CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(_CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
