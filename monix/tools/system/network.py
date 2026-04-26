from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path


def network_io(is_linux: bool | None = None, sample_seconds: float = 1.0) -> list[dict]:
    """Returns per-interface bytes/packets per second over a 1-second sample."""
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _network_io_linux(sample_seconds)
    return _network_io_macos(sample_seconds)


def _network_io_linux(sample_seconds: float) -> list[dict]:
    first = _read_proc_net()
    if first is None:
        return []
    time.sleep(sample_seconds)
    second = _read_proc_net()
    if second is None:
        return []

    results = []
    for iface, s2 in second.items():
        if iface not in first:
            continue
        s1 = first[iface]
        dt = max(sample_seconds, 0.001)
        rx_bps = (s2["rx_bytes"] - s1["rx_bytes"]) / dt
        tx_bps = (s2["tx_bytes"] - s1["tx_bytes"]) / dt
        results.append({
            "interface": iface,
            "rx_bytes_total": s2["rx_bytes"],
            "tx_bytes_total": s2["tx_bytes"],
            "rx_bps": max(rx_bps, 0),
            "tx_bps": max(tx_bps, 0),
        })
    results = _filter_active(results)
    results.sort(key=lambda x: x["rx_bps"] + x["tx_bps"], reverse=True)
    return results


def _filter_active(interfaces: list[dict]) -> list[dict]:
    """Keep only interfaces with meaningful traffic (>= 1 KiB total)."""
    active = [
        i for i in interfaces
        if i["rx_bytes_total"] + i["tx_bytes_total"] >= 1024
    ]
    return active if active else interfaces


def _read_proc_net() -> dict | None:
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    result = {}
    for line in lines[2:]:
        parts = line.split(":")
        if len(parts) < 2:
            continue
        iface = parts[0].strip()
        if iface == "lo":
            continue
        fields = parts[1].split()
        if len(fields) < 9:
            continue
        result[iface] = {"rx_bytes": int(fields[0]), "tx_bytes": int(fields[8])}
    return result


def _network_io_macos(sample_seconds: float) -> list[dict]:
    def _sample() -> dict | None:
        try:
            out = subprocess.check_output(
                ["netstat", "-ib"], text=True, timeout=3, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        result: dict[str, dict] = {}
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 10:
                continue
            iface = parts[0]
            if iface.startswith("lo") or "<Link#" not in line:
                continue
            try:
                rx = int(parts[6])
                tx = int(parts[9])
            except (ValueError, IndexError):
                continue
            if iface not in result:
                result[iface] = {"rx_bytes": rx, "tx_bytes": tx}
        return result

    first = _sample()
    if first is None:
        return []
    time.sleep(sample_seconds)
    second = _sample()
    if second is None:
        return []

    results = []
    for iface, s2 in second.items():
        if iface not in first:
            continue
        s1 = first[iface]
        dt = max(sample_seconds, 0.001)
        rx_bps = (s2["rx_bytes"] - s1["rx_bytes"]) / dt
        tx_bps = (s2["tx_bytes"] - s1["tx_bytes"]) / dt
        results.append({
            "interface": iface,
            "rx_bytes_total": s2["rx_bytes"],
            "tx_bytes_total": s2["tx_bytes"],
            "rx_bps": max(rx_bps, 0),
            "tx_bps": max(tx_bps, 0),
        })
    results = _filter_active(results)
    results.sort(key=lambda x: x["rx_bps"] + x["tx_bps"], reverse=True)
    return results
