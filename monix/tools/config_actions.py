from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _parse_duration_days(s: str) -> float:
    s = s.strip().lower()
    units = {"s": 1 / 86400, "m": 1 / 1440, "h": 1 / 24, "d": 1.0}
    for suffix, factor in units.items():
        if s.endswith(suffix):
            return float(s[:-1]) * factor
    return float(s)


def _fmt_duration(days: float) -> str:
    secs = days * 86400
    if secs < 60:
        return f"{secs:.0f}s"
    if secs < 3600:
        return f"{secs / 60:.0f}m"
    if secs < 86400:
        return f"{secs / 3600:.1f}h"
    return f"{days:.1f}d"


def log_add(
    alias: str,
    log_type: str,
    path: str | None = None,
    container: str | None = None,
) -> dict[str, Any]:
    from monix.tools.logs.registry import add
    try:
        entry, is_new = add(alias, log_type, path=path, container=container)
    except ValueError as exc:
        return {"error": str(exc)}
    action = "등록" if is_new else "업데이트"
    detail = f"-> {entry.path}" if entry.path else f"-> container:{entry.container}"
    return {"result": f"[{action}] {log_type} 로그: @{alias} {detail}"}


def notify_set_webhook(platform: str, url: str | None = None) -> dict[str, Any]:
    from monix.tools.notify.config_store import set_notify_field
    if platform not in ("discord", "slack"):
        return {"error": "platform은 'discord' 또는 'slack'이어야 합니다."}
    key = "discord_url" if platform == "discord" else "slack_url"
    set_notify_field(key, url or None)
    if url:
        return {"result": f"{platform.title()} 웹훅 URL 저장됨."}
    return {"result": f"{platform.title()} 웹훅 URL 삭제됨."}


def notify_set_metric_alert(metric: str, enabled: bool) -> dict[str, Any]:
    from monix.tools.notify.config_store import set_notify_field
    if metric not in ("cpu", "memory", "disk"):
        return {"error": "metric은 'cpu', 'memory', 'disk' 중 하나여야 합니다."}
    set_notify_field(metric, enabled)
    state = "활성화" if enabled else "비활성화"
    return {"result": f"{metric.upper()} 메트릭 알림 {state}됨."}


def notify_set_cooldown(seconds: int) -> dict[str, Any]:
    from monix.tools.notify.config_store import set_notify_field
    if seconds < 0:
        return {"error": "cooldown은 0 이상이어야 합니다."}
    set_notify_field("cooldown", seconds)
    return {"result": f"메트릭 알림 쿨다운이 {seconds}초로 설정됨."}


def notify_set_log_errors(enabled: bool) -> dict[str, Any]:
    from monix.tools.notify.config_store import set_notify_field
    set_notify_field("log_errors", enabled)
    state = "활성화" if enabled else "비활성화"
    return {"result": f"로그 에러 알림 {state}됨."}


def notify_set_log_severity(severity: str) -> dict[str, Any]:
    from monix.tools.notify.config_store import set_notify_field
    if severity not in ("error", "warn"):
        return {"error": "severity는 'error' 또는 'warn'이어야 합니다."}
    set_notify_field("log_severity", severity)
    return {"result": f"로그 알림 최소 심각도가 '{severity}'로 설정됨."}


def notify_set_log_cooldown(seconds: int) -> dict[str, Any]:
    from monix.tools.notify.config_store import set_notify_field
    if seconds < 0:
        return {"error": "log_cooldown은 0 이상이어야 합니다."}
    set_notify_field("log_cooldown", seconds)
    return {"result": f"로그 알림 쿨다운이 {seconds}초로 설정됨."}


def notify_add_log_ignore(pattern: str) -> dict[str, Any]:
    from monix.tools.notify.config_store import load_notify_config, save_notify_config
    if not pattern.strip():
        return {"error": "패턴이 비어있습니다."}
    cfg = load_notify_config()
    lst: list = cfg.get("log_ignore", [])
    if pattern in lst:
        return {"result": f"이미 무시 목록에 있습니다: {pattern!r}"}
    save_notify_config({**cfg, "log_ignore": lst + [pattern]})
    return {"result": f"무시 패턴 추가됨: {pattern!r}"}


def collect_set_config(interval: str, retention: str, folder: str) -> dict[str, Any]:
    from monix.tools.collect import CollectorConfig, save_config
    try:
        interval_days = _parse_duration_days(interval)
        retention_days = _parse_duration_days(retention)
    except (ValueError, TypeError):
        return {"error": "유효하지 않은 기간 형식입니다. 예: '1h', '30d', '0.5'"}
    if interval_days <= 0:
        return {"error": "interval은 0보다 커야 합니다."}
    if retention_days <= 0:
        return {"error": "retention은 0보다 커야 합니다."}
    path = Path(folder).expanduser().resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return {"error": f"폴더 생성 권한 없음: {path}"}
    except OSError as exc:
        return {"error": f"폴더 생성 실패: {exc}"}
    if not os.access(path, os.W_OK):
        return {"error": f"쓰기 권한 없음: {path}"}
    cfg = CollectorConfig(interval_days=interval_days, retention_days=retention_days, folder=str(path))
    save_config(cfg)
    return {
        "result": (
            f"히스토리 수집 설정 완료\n"
            f"  수집 간격: {_fmt_duration(interval_days)}\n"
            f"  보존 기간: {_fmt_duration(retention_days)}\n"
            f"  저장 폴더: {path}"
        )
    }
