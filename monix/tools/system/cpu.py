from __future__ import annotations

import platform
import subprocess
import time
import re
from pathlib import Path


def cpu_usage_percent(is_linux: bool | None = None, sample_seconds: float = 0.25) -> float | None:
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _cpu_usage_linux(sample_seconds)
    return _cpu_usage_macos()


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


def _cpu_usage_macos() -> float | None:
    """Return overall CPU usage percentage by sampling 'top -l 2'."""
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
                idle = float(m.group(1))
    if idle is None:
        return None
    return round(100 - idle, 1)


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
