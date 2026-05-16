from __future__ import annotations

from typing import TypedDict


class AlertFilter(TypedDict, total=False):
    cpu: bool
    memory: bool
    disk: bool


class NotifyConfig(TypedDict, total=False):
    discord_url: str | None
    slack_url: str | None
    cooldown_seconds: int
    state_path: str
    alert_filter: AlertFilter
