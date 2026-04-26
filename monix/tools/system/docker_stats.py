from __future__ import annotations

import json
import subprocess


def container_stats(container: str | None = None) -> list[dict]:
    """docker stats --no-stream 결과를 파싱해 반환."""
    cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
    if container:
        cmd.append(container)
    try:
        output = subprocess.check_output(cmd, text=True, timeout=15, stderr=subprocess.PIPE)
        result = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result
    except FileNotFoundError:
        return [{"error": "docker command not found"}]
    except subprocess.TimeoutExpired:
        return [{"error": "timeout"}]
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or str(exc)).strip()
        return [{"error": msg or "docker stats failed"}]
    except OSError as exc:
        return [{"error": str(exc)}]


def container_processes(container: str) -> dict:
    """docker top <container> 결과를 파싱해 반환."""
    try:
        output = subprocess.check_output(
            ["docker", "top", container],
            text=True,
            timeout=10,
            stderr=subprocess.STDOUT,
        )
        lines = output.splitlines()
        if not lines:
            return {"container": container, "status": "ok", "headers": [], "rows": []}
        headers = lines[0].split()
        rows = []
        for line in lines[1:]:
            if line.strip():
                rows.append(line.split(maxsplit=len(headers) - 1))
        return {"container": container, "status": "ok", "headers": headers, "rows": rows}
    except FileNotFoundError:
        return {"container": container, "status": "error", "error": "docker command not found"}
    except subprocess.TimeoutExpired:
        return {"container": container, "status": "error", "error": "timeout"}
    except subprocess.CalledProcessError as exc:
        return {"container": container, "status": "error", "error": (exc.output or str(exc)).strip()}
    except OSError as exc:
        return {"container": container, "status": "error", "error": str(exc)}


def container_inspect(container: str) -> dict:
    """docker inspect <container> 결과에서 주요 필드를 파싱해 반환."""
    try:
        output = subprocess.check_output(
            ["docker", "inspect", container],
            text=True,
            timeout=10,
            stderr=subprocess.PIPE,
        )
        data = json.loads(output)
        if not data:
            return {"container": container, "status": "error", "error": "not found"}
        info = data[0]

        port_bindings = ((info.get("NetworkSettings") or {}).get("Ports")) or {}
        ports = []
        for cport, host_list in port_bindings.items():
            if host_list:
                for binding in host_list:
                    host_ip = binding.get("HostIp") or "0.0.0.0"
                    host_port = binding.get("HostPort") or "?"
                    ports.append(f"{host_ip}:{host_port} -> {cport}")
            else:
                ports.append(f"(unbound) -> {cport}")

        mounts = [
            {
                "type": m.get("Type", ""),
                "source": m.get("Source", ""),
                "destination": m.get("Destination", ""),
                "mode": m.get("Mode", ""),
            }
            for m in (info.get("Mounts") or [])
        ]

        state = info.get("State") or {}
        health = state.get("Health") or {}
        networks = list(((info.get("NetworkSettings") or {}).get("Networks") or {}).keys())

        return {
            "container": container,
            "status": "ok",
            "name": (info.get("Name") or "").lstrip("/"),
            "image": (info.get("Config") or {}).get("Image", ""),
            "state": state.get("Status", "unknown"),
            "started_at": state.get("StartedAt", ""),
            "restart_count": info.get("RestartCount", 0),
            "health_status": health.get("Status", "none"),
            "ports": ports,
            "mounts": mounts,
            "env": (info.get("Config") or {}).get("Env") or [],
            "networks": networks,
            "ip_address": (info.get("NetworkSettings") or {}).get("IPAddress") or "",
        }
    except FileNotFoundError:
        return {"container": container, "status": "error", "error": "docker command not found"}
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        return {"container": container, "status": "error", "error": f"parse error: {exc}"}
    except subprocess.TimeoutExpired:
        return {"container": container, "status": "error", "error": "timeout"}
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or str(exc)).strip()
        return {"container": container, "status": "error", "error": msg or "docker inspect failed"}
    except OSError as exc:
        return {"container": container, "status": "error", "error": str(exc)}
