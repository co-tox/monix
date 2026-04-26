from __future__ import annotations

import shutil
import subprocess


def service_status(name: str) -> dict:
    name = name.strip()
    if not name:
        return {"name": name, "status": "unknown", "details": "service name is empty"}
    if shutil.which("systemctl"):
        try:
            output = subprocess.check_output(
                ["systemctl", "status", name, "--no-pager", "--lines", "20"],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=5,
            )
            return {"name": name, "status": "ok", "details": output.strip()}
        except subprocess.CalledProcessError as exc:
            return {"name": name, "status": "error", "details": exc.output.strip()}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"name": name, "status": "error", "details": str(exc)}
    return {"name": name, "status": "unknown", "details": "systemctl is not available on this host"}
