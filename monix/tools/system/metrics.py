from __future__ import annotations

import os
import platform
import subprocess
import time
from pathlib import Path

from monix.config import Settings
from monix.tools.system.cpu import cpu_usage_percent
from monix.tools.system.disk import disk_info
from monix.tools.system.memory import memory_info
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
        "memory": memory_info(is_linux=is_linux),
        "disks": disk_info(),
        "top_processes": top_processes(limit=5),
    }
    snapshot["alerts"] = build_alerts(snapshot, settings.thresholds)
    return snapshot


def build_alerts(snapshot: dict, thresholds) -> list[str]:
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


def load_average() -> tuple[float, float, float] | None:
    try:
        return tuple(round(v, 2) for v in os.getloadavg())
    except OSError:
        return None


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


def _uptime_linux() -> int | None:
    try:
        return int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return None


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
