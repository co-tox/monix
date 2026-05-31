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


class LogAlertConfig(TypedDict, total=False):
    enabled: bool           # 기본값: False
    min_severity: str       # "error" | "warn", 기본값: "error"
    cooldown_seconds: int   # 기본값: 300
    max_lines: int          # 웹훅에 포함할 최대 라인 수, 기본값: 5
