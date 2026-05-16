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


def _alert_label(alert: str) -> str:
    if alert.startswith("CPU"):
        return "CPU"
    if alert.startswith("Memory"):
        return "Memory"
    if alert.startswith("Disk"):
        return "Disk"
    return "Alert"
