from __future__ import annotations

import shutil
import subprocess


def list_services() -> dict:
    if shutil.which("systemctl"):
        try:
            output = subprocess.check_output(
                [
                    "systemctl", "list-units",
                    "--type=service",
                    "--no-pager",
                    "--no-legend",
                    "--plain",
                ],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=5,
            )
            services = []
            for line in output.splitlines():
                parts = line.split(None, 4)
                if len(parts) < 4:
                    continue
                unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
                desc = parts[4].strip() if len(parts) > 4 else ""
                services.append({
                    "name": unit,
                    "load": load,
                    "active": active,
                    "sub": sub,
                    "description": desc,
                })
            return {"status": "ok", "services": services}
        except subprocess.CalledProcessError as exc:
            return {"status": "error", "services": [], "details": exc.output.strip()}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "error", "services": [], "details": str(exc)}
    return {"status": "unknown", "services": [], "details": "systemctl is not available on this host"}


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
