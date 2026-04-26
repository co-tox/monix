from __future__ import annotations

import shutil
from typing import Iterable


def disk_info(paths: Iterable[str] = ("/",)) -> list[dict]:
    disks = []
    for path in paths:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        percent = round((usage.used / usage.total) * 100, 1) if usage.total else None
        disks.append({
            "path": path,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": percent,
        })
    return disks
