from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from monix.tools.notify._types import AlertFilter, NotifyConfig
from monix.tools.notify.discord import build_discord_payload
from monix.tools.notify.slack import build_slack_payload
from monix.tools.notify.webhook import _post_json

__all__ = ["AlertFilter", "NotifyConfig", "filter_alerts", "send_alert"]

_DEFAULT_STATE_PATH = Path.home() / ".monix" / "notify_state.json"
_DEFAULT_COOLDOWN = 3600

_PREFIXES: dict[str, str] = {
    "cpu": "CPU usage",
    "memory": "Memory usage",
    "disk": "Disk usage",
}


def filter_alerts(alerts: list[str], alert_filter: AlertFilter) -> list[str]:
    result = []
    for alert in alerts:
        for key, prefix in _PREFIXES.items():
            if alert.startswith(prefix):
                if alert_filter.get(key, True):
                    result.append(alert)
                break
        else:
            result.append(alert)
    return result


def send_alert(alerts: list[str], host: str, config: NotifyConfig) -> list[str]:
    """alerts를 설정된 웹훅(들)로 발송. 실패한 채널 이름 목록을 반환."""
    af: AlertFilter = config.get("alert_filter", AlertFilter())
    filtered = filter_alerts(alerts, af)
    filtered = _apply_cooldown(filtered, config)
    if not filtered:
        return []

    payload_d = build_discord_payload(filtered, host)
    payload_s = build_slack_payload(filtered, host)
    failed: list[str] = []

    if url := config.get("discord_url"):
        try:
            _post_json(url, payload_d)
        except Exception as e:
            print(f"[monix] discord webhook failed: {e}", file=sys.stderr)
            failed.append("discord")

    if url := config.get("slack_url"):
        try:
            _post_json(url, payload_s)
        except Exception as e:
            print(f"[monix] slack webhook failed: {e}", file=sys.stderr)
            failed.append("slack")

    _save_cooldown_state(filtered, config)
    return failed


def _alert_key(alert: str) -> str:
    return hashlib.sha1(alert.encode()).hexdigest()[:8]


def _state_path(config: NotifyConfig) -> Path:
    raw = config.get("state_path")
    return Path(raw) if raw else _DEFAULT_STATE_PATH


def _load_state(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _apply_cooldown(alerts: list[str], config: NotifyConfig) -> list[str]:
    cooldown = config.get("cooldown_seconds", _DEFAULT_COOLDOWN)
    if cooldown <= 0:
        return alerts
    state = _load_state(_state_path(config))
    now = datetime.now()
    result = []
    for alert in alerts:
        key = _alert_key(alert)
        last_raw = state.get(key)
        if last_raw:
            try:
                last = datetime.fromisoformat(last_raw)
                if (now - last).total_seconds() < cooldown:
                    continue
            except ValueError:
                pass
        result.append(alert)
    return result


def _save_cooldown_state(alerts: list[str], config: NotifyConfig) -> None:
    path = _state_path(config)
    state = _load_state(path)
    now = datetime.now().isoformat()
    for alert in alerts:
        state[_alert_key(alert)] = now
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print(f"[monix] failed to save notify state: {e}", file=sys.stderr)
