from __future__ import annotations

import ctypes
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


def cpu_core_usage_percents(is_linux: bool | None = None, sample_seconds: float = 0.25) -> list[float]:
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _cpu_core_usage_linux(sample_seconds)
    return _cpu_core_usage_macos(sample_seconds)


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


def _cpu_core_usage_linux(sample_seconds: float) -> list[float]:
    first = _read_proc_stats()
    if not first:
        return []
    time.sleep(sample_seconds)
    second = _read_proc_stats()
    if not second:
        return []

    result = []
    for name in sorted(first, key=_cpu_sort_key):
        if name == "cpu" or name not in second:
            continue
        idle_delta = second[name]["idle"] - first[name]["idle"]
        total_delta = second[name]["total"] - first[name]["total"]
        if total_delta <= 0 or idle_delta < 0:
            result.append(None)
        else:
            result.append(round((1 - idle_delta / total_delta) * 100, 1))
    return [value for value in result if value is not None]


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


def _cpu_core_usage_macos(sample_seconds: float) -> list[float]:
    first = _read_macos_cpu_ticks()
    if not first:
        return []
    time.sleep(sample_seconds)
    second = _read_macos_cpu_ticks()
    if not second or len(first) != len(second):
        return []

    result = []
    for before, after in zip(first, second):
        idle_delta = after["idle"] - before["idle"]
        total_delta = after["total"] - before["total"]
        if total_delta <= 0 or idle_delta < 0:
            continue
        result.append(round((1 - idle_delta / total_delta) * 100, 1))
    return result


def _read_proc_stat() -> dict | None:
    stats = _read_proc_stats()
    return stats.get("cpu") if stats else None


def _read_proc_stats() -> dict[str, dict[str, int]] | None:
    try:
        lines = Path("/proc/stat").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    stats = {}
    for line in lines:
        fields = line.split()
        if not fields or not re.fullmatch(r"cpu\d*|cpu", fields[0]):
            continue
        try:
            values = [int(v) for v in fields[1:]]
        except ValueError:
            continue
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        stats[fields[0]] = {"idle": idle, "total": sum(values)}
    return stats or None


def _read_macos_cpu_ticks() -> list[dict[str, int]]:
    if platform.system() != "Darwin":
        return []
    try:
        lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
        processor_count = ctypes.c_uint()
        processor_info = ctypes.POINTER(ctypes.c_int)()
        processor_info_count = ctypes.c_uint()
        result = lib.host_processor_info(
            lib.mach_host_self(),
            2,  # PROCESSOR_CPU_LOAD_INFO
            ctypes.byref(processor_count),
            ctypes.byref(processor_info),
            ctypes.byref(processor_info_count),
        )
    except (OSError, AttributeError, TypeError):
        return []
    if result != 0:
        return []

    cpus = []
    try:
        for i in range(processor_count.value):
            offset = i * 4
            user = int(processor_info[offset])
            system = int(processor_info[offset + 1])
            idle = int(processor_info[offset + 2])
            nice = int(processor_info[offset + 3])
            cpus.append({"idle": idle, "total": user + system + idle + nice})
    finally:
        _macos_vm_deallocate(lib, processor_info, processor_info_count.value)
    return cpus


def _macos_vm_deallocate(lib, processor_info, processor_info_count: int) -> None:
    try:
        task_self = lib.mach_task_self()
        address = ctypes.cast(processor_info, ctypes.c_void_p).value
        size = processor_info_count * ctypes.sizeof(ctypes.c_int)
        if address:
            lib.vm_deallocate(task_self, address, size)
    except (AttributeError, TypeError):
        pass


def _cpu_sort_key(name: str) -> int:
    if name == "cpu":
        return -1
    return int(name[3:])
