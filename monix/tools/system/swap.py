from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def swap_info(is_linux: bool | None = None) -> dict:
    if is_linux is None:
        is_linux = platform.system() == "Linux"
    if is_linux:
        return _swap_linux()
    return _swap_macos()


def _swap_linux() -> dict:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if not line.startswith("Swap"):
                continue
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        total = values.get("SwapTotal", 0)
        free = values.get("SwapFree", 0)
        used = max(total - free, 0)
        percent = round((used / total) * 100, 1) if total else 0.0
        return {"total": total, "used": used, "free": free, "percent": percent}
    except OSError:
        return {"total": None, "used": None, "free": None, "percent": None}


def _swap_macos() -> dict:
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "vm.swapusage"], text=True, timeout=2, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return {"total": None, "used": None, "free": None, "percent": None}
    # format: total = 2048.00M  used = 512.00M  free = 1536.00M
    def _parse_mb(token: str) -> int | None:
        try:
            num_str = token.rstrip("MKG")
            num = float(num_str)
            if token.endswith("G"):
                return int(num * 1024 * 1024 * 1024)
            if token.endswith("K"):
                return int(num * 1024)
            return int(num * 1024 * 1024)
        except ValueError:
            return None

    parts = out.split()
    vals: dict[str, int | None] = {}
    for i, p in enumerate(parts):
        if p in ("total", "used", "free") and i + 2 < len(parts):
            vals[p] = _parse_mb(parts[i + 2])
    total = vals.get("total") or 0
    used = vals.get("used") or 0
    free = vals.get("free") or 0
    percent = round((used / total) * 100, 1) if total else 0.0
    return {"total": total, "used": used, "free": free, "percent": percent}
