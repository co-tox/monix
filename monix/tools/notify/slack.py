from __future__ import annotations

from datetime import datetime


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
