from __future__ import annotations

import os
import platform
import subprocess


def memory_info(is_linux: bool | None = None) -> dict:
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _memory_linux()
    return _memory_macos()


def _memory_linux() -> dict:
    try:
        values = {}
        for line in open("/proc/meminfo", encoding="utf-8"):
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = max(total - available, 0)
        percent = round((used / total) * 100, 1) if total else None
        return {"total": total, "available": available, "used": used, "percent": percent}
    except OSError:
        return {"total": None, "available": None, "used": None, "percent": None}


def _memory_macos() -> dict:
    try:
        output = subprocess.check_output(["vm_stat"], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return {"total": None, "available": None, "used": None, "percent": None}

    page_size = 4096
    pages: dict[str, int] = {}
    for line in output.splitlines():
        if "page size of" in line:
            for part in line.split():
                if part.isdigit():
                    page_size = int(part)
                    break
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw_value = raw.strip().rstrip(".")
        if raw_value.isdigit():
            pages[key.strip()] = int(raw_value)

    free_pages = pages.get("Pages free", 0) + pages.get("Pages inactive", 0) + pages.get("Pages speculative", 0)
    total_pages = _physical_pages() or sum(v for k, v in pages.items() if k.startswith("Pages"))
    used_pages = max(total_pages - free_pages, 0)
    total_bytes = total_pages * page_size
    used_bytes = used_pages * page_size
    available_bytes = free_pages * page_size
    percent = round((used_bytes / total_bytes) * 100, 1) if total_bytes else None
    return {"total": total_bytes, "available": available_bytes, "used": used_bytes, "percent": percent}


def _physical_pages() -> int | None:
    try:
        return int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None
