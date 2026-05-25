from __future__ import annotations

from datetime import datetime


def build_discord_payload(alerts: list[str], host: str) -> dict:
    color = 0xFF0000 if len(alerts) > 1 else 0xFF8C00
    fields = [{"name": _alert_label(a), "value": a, "inline": False} for a in alerts]
    return {
        "embeds": [{
            "title": f"⚠ Monix Alert — {host}",
            "color": color,
            "fields": fields,
            "footer": {"text": "monix"},
            "timestamp": datetime.utcnow().isoformat(),
        }]
    }


def build_discord_log_payload(lines: list[str], source: str, severity: str, host: str) -> dict:
    color = 0xFF0000 if severity == "error" else 0xFF8C00
    label = "ERROR" if severity == "error" else "WARN"
    body = "\n".join(f"`{ln}`" for ln in lines) if lines else "(no lines captured)"
    return {
        "embeds": [{
            "title": f"⚠ Log {label} — {host}",
            "color": color,
            "fields": [
                {"name": "Source", "value": source, "inline": False},
                {"name": f"Recent {label} Lines", "value": body, "inline": False},
            ],
            "footer": {"text": "monix"},
            "timestamp": datetime.utcnow().isoformat(),
        }]
    }


def _alert_label(alert: str) -> str:
    if alert.startswith("CPU"):
        return "CPU"
    if alert.startswith("Memory"):
        return "Memory"
    if alert.startswith("Disk"):
        return "Disk"
    return "Alert"
