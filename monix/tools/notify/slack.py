from __future__ import annotations

from datetime import datetime


def build_slack_log_payload(lines: list[str], source: str, severity: str, host: str) -> dict:
    label = "ERROR" if severity == "error" else "WARN"
    body = "\n".join(f"• `{ln}`" for ln in lines) if lines else "(no lines captured)"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"⚠ Log {label} — {host}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Source*\n{source}"},
                    {"type": "mrkdwn", "text": f"*Severity*\n{label}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"monix | {ts}"}],
            },
        ]
    }


def build_slack_payload(alerts: list[str], host: str) -> dict:
    body = "\n".join(f"• {a}" for a in alerts)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"⚠ Monix Alert — {host}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"monix | {ts}"}],
            },
        ]
    }
