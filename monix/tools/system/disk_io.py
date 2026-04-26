from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path


def disk_io(is_linux: bool | None = None, sample_seconds: float = 1.0) -> list[dict]:
    """Returns per-device read/write KB/s over a 1-second sample."""
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _disk_io_linux(sample_seconds)
    return _disk_io_macos(sample_seconds)


def _disk_io_linux(sample_seconds: float) -> list[dict]:
    first = _read_diskstats()
    if first is None:
        return []
    time.sleep(sample_seconds)
    second = _read_diskstats()
    if second is None:
        return []

    results = []
    for dev, s2 in second.items():
        if dev not in first:
            continue
        s1 = first[dev]
        dt = max(sample_seconds, 0.001)
        # /proc/diskstats fields 3,7 are sectors read/written (512 bytes each)
        read_bps = (s2["read_sectors"] - s1["read_sectors"]) * 512 / dt
        write_bps = (s2["write_sectors"] - s1["write_sectors"]) * 512 / dt
        if read_bps < 0:
            read_bps = 0
        if write_bps < 0:
            write_bps = 0
        results.append({"device": dev, "read_bps": read_bps, "write_bps": write_bps})
    results.sort(key=lambda x: x["read_bps"] + x["write_bps"], reverse=True)
    return results


def _read_diskstats() -> dict | None:
    try:
        lines = Path("/proc/diskstats").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    result: dict[str, dict] = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 10:
            continue
        dev = parts[2]
        # skip partitions (e.g. sda1, nvme0n1p1)
        if any(c.isdigit() for c in dev[-2:]) and not dev.endswith("d0"):
            continue
        result[dev] = {"read_sectors": int(parts[5]), "write_sectors": int(parts[9])}
    return result


def _disk_io_macos(sample_seconds: float) -> list[dict]:
    # iostat -c 2 output:
    #               disk0
    #     KB/t  tps  MB/s
    #    19.79  162  3.13    <- sample 1 (cumulative since boot)
    #    14.30   87  1.21    <- sample 2 (rate since last sample = actual current rate)
    try:
        out = subprocess.check_output(
            ["iostat", "-d", "-K", "-c", "2"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    lines = out.splitlines()
    # Line 0: device names (e.g. "              disk0")
    # Line 1: column headers "    KB/t  tps  MB/s"
    # Line 2: first sample
    # Line 3: second sample (actual per-second rate)
    if len(lines) < 4:
        return []

    dev_names = lines[0].split()
    data_parts = lines[3].split()  # second sample is current rate

    results = []
    for i, dev in enumerate(dev_names):
        offset = i * 3
        if offset + 2 >= len(data_parts):
            break
        try:
            mb_per_sec = float(data_parts[offset + 2])
            bps = mb_per_sec * 1024 * 1024
            results.append({"device": dev, "read_bps": bps, "write_bps": 0})
        except (ValueError, IndexError):
            continue
    results.sort(key=lambda x: x["read_bps"] + x["write_bps"], reverse=True)
    return results
