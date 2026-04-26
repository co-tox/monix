from __future__ import annotations

import subprocess
from typing import Iterator


def tail_container(container: str, lines: int = 80) -> dict:
    """Fetch the last N lines from a Docker container's log."""
    try:
        output = subprocess.check_output(
            ["docker", "logs", "--tail", str(lines), container],
            text=True,
            timeout=10,
            stderr=subprocess.STDOUT,
        )
        return {"path": f"docker://{container}", "status": "ok", "lines": output.splitlines()}
    except FileNotFoundError:
        return {"path": f"docker://{container}", "status": "error", "lines": ["docker 명령을 찾을 수 없습니다."]}
    except subprocess.TimeoutExpired:
        return {"path": f"docker://{container}", "status": "error", "lines": ["타임아웃"]}
    except subprocess.CalledProcessError as exc:
        lines_out = (exc.output or "").splitlines()
        return {"path": f"docker://{container}", "status": "error", "lines": lines_out or [str(exc)]}
    except OSError as exc:
        return {"path": f"docker://{container}", "status": "error", "lines": [str(exc)]}


def follow_container(container: str, initial_lines: int = 20) -> Iterator[str]:
    """Yield container log lines in real-time. Caller handles KeyboardInterrupt."""
    proc = subprocess.Popen(
        ["docker", "logs", "--tail", str(initial_lines), "-f", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert proc.stdout
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.terminate()
        proc.wait()


def list_containers() -> list[dict]:
    """Return a list of running Docker containers with name, status, image."""
    try:
        output = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
            text=True,
            timeout=5,
        )
        result = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                result.append({"name": parts[0], "status": parts[1], "image": parts[2]})
        return result
    except Exception:
        return []
