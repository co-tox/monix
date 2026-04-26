from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

from monix.config import Settings, Thresholds
from monix.tools.system.processes import top_processes


def collect_snapshot(settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    is_linux = settings.platform not in ("mac", "darwin")
    uptime_seconds = uptime_seconds_value(is_linux)
    snapshot = {
        "host": platform.node() or "unknown",
        "os": f"{platform.system()} {platform.release()}",
        "time": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "uptime_seconds": uptime_seconds,
        "uptime": human_duration(uptime_seconds) if uptime_seconds is not None else "unknown",
        "load_average": load_average(),
        "cpu_percent": cpu_usage_percent(is_linux=is_linux),
        "memory": memory_info(is_linux),
        "disks": disk_info(),
        "top_processes": top_processes(limit=5),
    }
    snapshot["alerts"] = build_alerts(snapshot, settings.thresholds)
    return snapshot


def cpu_usage_percent(sample_seconds: float = 0.25, is_linux: bool | None = None) -> float | None:
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _cpu_usage_linux(sample_seconds)
    return _cpu_usage_macos()


def load_average() -> tuple[float, float, float] | None:
    try:
        return tuple(round(v, 2) for v in os.getloadavg())
    except OSError:
        return None


def memory_info(is_linux: bool | None = None) -> dict:
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _memory_linux()
    return _memory_macos()


def disk_info(paths: Iterable[str] = ("/",)) -> list[dict]:
    disks = []
    for path in paths:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        percent = round((usage.used / usage.total) * 100, 1) if usage.total else None
        disks.append({"path": path, "total": usage.total, "used": usage.used, "free": usage.free, "percent": percent})
    return disks


def build_alerts(snapshot: dict, thresholds: Thresholds) -> list[str]:
    alerts = []
    cpu = snapshot.get("cpu_percent")
    if cpu is not None and cpu >= thresholds.cpu_warn:
        alerts.append(f"CPU usage is high: {cpu}% >= {thresholds.cpu_warn}%")
    mem_percent = snapshot.get("memory", {}).get("percent")
    if mem_percent is not None and mem_percent >= thresholds.mem_warn:
        alerts.append(f"Memory usage is high: {mem_percent}% >= {thresholds.mem_warn}%")
    for disk in snapshot.get("disks", []):
        percent = disk.get("percent")
        if percent is not None and percent >= thresholds.disk_warn:
            alerts.append(f"Disk usage is high on {disk['path']}: {percent}% >= {thresholds.disk_warn}%")
    return alerts


def uptime_seconds_value(is_linux: bool | None = None) -> int | None:
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _uptime_linux()
    return _uptime_macos()


def human_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def human_duration(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


# ── Linux ──────────────────────────────────────────────────────────────────

def _cpu_usage_linux(sample_seconds: float) -> float | None:
    first = _read_proc_stat()
    if first is None:
        return None
    time.sleep(sample_seconds)
    second = _read_proc_stat()
    if second is None:
        return None
    idle_delta = second["idle"] - first["idle"]
    total_delta = second["total"] - first["total"]
    if total_delta <= 0 or idle_delta < 0:
        return None
    return round((1 - idle_delta / total_delta) * 100, 1)


def _read_proc_stat() -> dict | None:
    try:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
    except OSError:
        return None
    if not fields or fields[0] != "cpu":
        return None
    values = [int(v) for v in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return {"idle": idle, "total": sum(values)}


def _memory_linux() -> dict:
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = max(total - available, 0)
        percent = round((used / total) * 100, 1) if total else None
        return {"total": total, "available": available, "used": used, "percent": percent}
    except OSError:
        return {"total": None, "available": None, "used": None, "percent": None}


def _uptime_linux() -> int | None:
    try:
        return int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return None


# ── macOS ──────────────────────────────────────────────────────────────────

def _cpu_usage_macos() -> float | None:
    """top -l 2 로 두 번 샘플링해 순간 CPU 사용률을 구합니다."""
    try:
        output = subprocess.check_output(
            ["top", "-l", "2", "-n", "0", "-s", "1"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    idle = None
    for line in output.splitlines():
        if "CPU usage:" in line:
            m = re.search(r"([\d.]+)%\s+idle", line)
            if m:
                idle = float(m.group(1))  # 마지막 샘플 값으로 덮어씀
    if idle is None:
        return None
    return round(100 - idle, 1)


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


def _uptime_macos() -> int | None:
    try:
        output = subprocess.check_output(
            ["sysctl", "-n", "kern.boottime"], text=True, stderr=subprocess.DEVNULL, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    marker = "sec = "
    if marker not in output:
        return None
    try:
        boot = int(output.split(marker, 1)[1].split(",", 1)[0])
    except (ValueError, IndexError):
        return None
    return max(int(time.time()) - boot, 0)


def _physical_pages() -> int | None:
    try:
        return int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None
