from __future__ import annotations

import subprocess
from pathlib import Path


def tail_log(path: str | Path, lines: int = 80) -> dict:
    log_path = Path(path).expanduser()
    if not log_path.exists():
        return {"path": str(log_path), "status": "missing", "lines": []}
    if not log_path.is_file():
        return {"path": str(log_path), "status": "not_file", "lines": []}
    try:
        output = subprocess.check_output(["tail", "-n", str(lines), str(log_path)], text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"path": str(log_path), "status": "error", "lines": [str(exc)]}
    return {"path": str(log_path), "status": "ok", "lines": output.splitlines()}
