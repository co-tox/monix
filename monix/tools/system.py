from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

from monix.config import Thresholds
from monix.tools.processes import top_processes


def collect_snapshot(thresholds: Thresholds | None = None) -> dict:
    thresholds = thresholds or Thresholds.from_env()
    uptime_seconds = uptime_seconds_value()
    memory = memory_info()
    disks = disk_info()
    cpu_percent = cpu_usage_percent()
    snapshot = {
        "host": platform.node() or "unknown",
        "os": f"{platform.system()} {platform.release()}",
        "time": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "uptime_seconds": uptime_seconds,
        "uptime": human_duration(uptime_seconds) if uptime_seconds is not None else "unknown",
        "load_average": load_average(),
        "cpu_percent": cpu_percent,
        "memory": memory,
        "disks": disks,
        "top_processes": top_processes(limit=5),
    }
    snapshot["alerts"] = build_alerts(snapshot, thresholds)
    return snapshot


def cpu_usage_percent(sample_seconds: float = 0.25) -> float | None:
    first = _read_proc_stat()
    if first is None:
        load = load_average()
        cpus = os.cpu_count() or 1
        if load:
            return round(min((load[0] / cpus) * 100, 100), 1)
        return None
    time.sleep(sample_seconds)
    second = _read_proc_stat()
    if second is None:
        return None
    idle_delta = second["idle"] - first["idle"]
    total_delta = second["total"] - first["total"]
    if total_delta <= 0:
        return None
    return round((1 - idle_delta / total_delta) * 100, 1)


def load_average() -> tuple[float, float, float] | None:
    if not hasattr(os, "getloadavg"):
        return None
    try:
        return tuple(round(value, 2) for value in os.getloadavg())
    except OSError:
        return None


def memory_info() -> dict:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {}
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = max(total - available, 0)
        percent = round((used / total) * 100, 1) if total else None
        return {"total": total, "available": available, "used": used, "percent": percent}

    try:
        output = subprocess.check_output(["vm_stat"], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return {"total": None, "available": None, "used": None, "percent": None}

    page_size = 4096
    pages = {}
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
    free = pages.get("Pages free", 0) + pages.get("Pages inactive", 0) + pages.get("Pages speculative", 0)
    total = _physical_pages()
    if total is None:
        total = sum(value for key, value in pages.items() if key.startswith("Pages"))
    used = max(total - free, 0)
    used_bytes = used * page_size
    total_bytes = total * page_size
    available = free * page_size
    percent = round((used_bytes / total_bytes) * 100, 1) if total_bytes else None
    return {"total": total_bytes, "available": available, "used": used_bytes, "percent": percent}


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


def uptime_seconds_value() -> int | None:
    path = Path("/proc/uptime")
    if path.exists():
        try:
            return int(float(path.read_text(encoding="utf-8").split()[0]))
        except (OSError, ValueError, IndexError):
            return None
    try:
        output = subprocess.check_output(["sysctl", "-n", "kern.boottime"], text=True, stderr=subprocess.DEVNULL, timeout=2)
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


def _read_proc_stat() -> dict | None:
    path = Path("/proc/stat")
    if not path.exists():
        return None
    fields = path.read_text(encoding="utf-8", errors="replace").splitlines()[0].split()
    if not fields or fields[0] != "cpu":
        return None
    values = [int(value) for value in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return {"idle": idle, "total": sum(values)}


def _physical_pages() -> int | None:
    try:
        return int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None
