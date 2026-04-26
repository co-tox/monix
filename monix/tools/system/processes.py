from __future__ import annotations

import subprocess


def top_processes(limit: int = 10) -> list[dict]:
    commands = (
        ["ps", "-eo", "pid,ppid,pcpu,pmem,comm", "--sort=-pcpu"],  # Linux
        ["ps", "-Ao", "pid,ppid,%cpu,%mem,comm"],                   # macOS
    )
    for command in commands:
        try:
            result = subprocess.run(
                command, text=True, timeout=3,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0 and result.stdout:
                return parse_ps(result.stdout, limit)
        except (OSError, subprocess.SubprocessError):
            continue
    return []


def parse_ps(output: str, limit: int, sort_by: str = "cpu") -> list[dict]:
    rows = []
    for line in output.splitlines()[1:]:
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            rows.append({
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "cpu": float(parts[2]),
                "mem": float(parts[3]),
                "command": parts[4],
            })
        except ValueError:
            continue
    rows.sort(key=lambda r: r.get(sort_by, 0), reverse=True)
    return rows[:limit]


def all_processes() -> list[dict]:
    """Return all processes without limiting or sorting."""
    commands = (
        ["ps", "-eo", "pid,ppid,pcpu,pmem,comm", "--sort=-pcpu"],
        ["ps", "-Ao", "pid,ppid,%cpu,%mem,comm"],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command, text=True, timeout=3,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0 and result.stdout:
                return parse_ps(result.stdout, limit=9999, sort_by="cpu")
        except (OSError, subprocess.SubprocessError):
            continue
    return []
