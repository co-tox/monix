from __future__ import annotations

import json
from pathlib import Path

import pytest

from monix.tools.config_actions import (
    _parse_duration_days,
    collect_set_config,
    log_add,
    notify_add_log_ignore,
    notify_set_cooldown,
    notify_set_log_cooldown,
    notify_set_log_errors,
    notify_set_log_severity,
    notify_set_metric_alert,
    notify_set_webhook,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    reg_dir = tmp_path / ".monix"
    reg_file = reg_dir / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", reg_dir)
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)
    import monix.tools.logs.registry as _reg
    _reg._cache = None
    _reg._cache_path = None


@pytest.fixture()
def notify_config_path(tmp_path, monkeypatch):
    cfg_path = tmp_path / ".monix" / "notify_config.json"
    monkeypatch.setattr("monix.tools.notify.config_store._CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.fixture()
def collector_config_path(tmp_path, monkeypatch):
    cfg_path = tmp_path / ".monix" / "collector.json"
    monkeypatch.setattr("monix.tools.collect.CONFIG_PATH", cfg_path)
    return cfg_path


# ── _parse_duration_days ─────────────────────────────────────────────────────

def test_parse_seconds():
    assert abs(_parse_duration_days("3600s") - (1 / 24)) < 1e-9


def test_parse_minutes():
    assert abs(_parse_duration_days("60m") - (1 / 24)) < 1e-9


def test_parse_hours():
    assert _parse_duration_days("1h") == pytest.approx(1 / 24)


def test_parse_days():
    assert _parse_duration_days("7d") == 7.0


def test_parse_bare_float():
    assert _parse_duration_days("0.5") == 0.5


# ── log_add ──────────────────────────────────────────────────────────────────

def test_log_add_app(tmp_path):
    result = log_add("api", "app", path="/var/log/api.log")
    assert "result" in result
    assert "등록" in result["result"]
    assert "@api" in result["result"]


def test_log_add_docker(tmp_path):
    result = log_add("web", "docker", container="web_container")
    assert "result" in result
    assert "docker" in result["result"]


def test_log_add_update_existing(tmp_path):
    log_add("api", "app", path="/old.log")
    result = log_add("api", "app", path="/new.log")
    assert "업데이트" in result["result"]


def test_log_add_invalid_type(tmp_path):
    result = log_add("bad", "unknown_type")
    assert "error" in result


# ── notify_set_webhook ────────────────────────────────────────────────────────

def test_notify_set_webhook_discord(notify_config_path):
    result = notify_set_webhook("discord", "https://discord.example/webhook")
    assert "result" in result
    assert "Discord" in result["result"]
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["discord_url"] == "https://discord.example/webhook"


def test_notify_set_webhook_slack(notify_config_path):
    result = notify_set_webhook("slack", "https://hooks.slack.com/xxx")
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["slack_url"] == "https://hooks.slack.com/xxx"


def test_notify_set_webhook_clear(notify_config_path):
    notify_set_webhook("discord", "https://discord.example/webhook")
    result = notify_set_webhook("discord")
    assert "삭제" in result["result"]
    cfg = json.loads(notify_config_path.read_text())
    assert cfg.get("discord_url") is None


def test_notify_set_webhook_invalid_platform(notify_config_path):
    result = notify_set_webhook("telegram", "https://example.com")
    assert "error" in result


# ── notify_set_metric_alert ──────────────────────────────────────────────────

def test_notify_set_metric_alert_cpu_on(notify_config_path):
    result = notify_set_metric_alert("cpu", True)
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["cpu"] is True


def test_notify_set_metric_alert_memory_off(notify_config_path):
    result = notify_set_metric_alert("memory", False)
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["memory"] is False


def test_notify_set_metric_alert_invalid(notify_config_path):
    result = notify_set_metric_alert("network", True)
    assert "error" in result


# ── notify_set_cooldown ───────────────────────────────────────────────────────

def test_notify_set_cooldown(notify_config_path):
    result = notify_set_cooldown(1800)
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["cooldown"] == 1800


def test_notify_set_cooldown_zero(notify_config_path):
    result = notify_set_cooldown(0)
    assert "result" in result


def test_notify_set_cooldown_negative(notify_config_path):
    result = notify_set_cooldown(-1)
    assert "error" in result


# ── notify_set_log_errors ────────────────────────────────────────────────────

def test_notify_set_log_errors_on(notify_config_path):
    result = notify_set_log_errors(True)
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["log_errors"] is True


def test_notify_set_log_errors_off(notify_config_path):
    result = notify_set_log_errors(False)
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["log_errors"] is False


# ── notify_set_log_severity ──────────────────────────────────────────────────

def test_notify_set_log_severity_warn(notify_config_path):
    result = notify_set_log_severity("warn")
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["log_severity"] == "warn"


def test_notify_set_log_severity_error(notify_config_path):
    result = notify_set_log_severity("error")
    assert "result" in result


def test_notify_set_log_severity_invalid(notify_config_path):
    result = notify_set_log_severity("critical")
    assert "error" in result


# ── notify_set_log_cooldown ──────────────────────────────────────────────────

def test_notify_set_log_cooldown(notify_config_path):
    result = notify_set_log_cooldown(600)
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["log_cooldown"] == 600


def test_notify_set_log_cooldown_negative(notify_config_path):
    result = notify_set_log_cooldown(-10)
    assert "error" in result


# ── notify_add_log_ignore ────────────────────────────────────────────────────

def test_notify_add_log_ignore(notify_config_path):
    result = notify_add_log_ignore("healthcheck")
    assert "result" in result
    cfg = json.loads(notify_config_path.read_text())
    assert "healthcheck" in cfg["log_ignore"]


def test_notify_add_log_ignore_duplicate(notify_config_path):
    notify_add_log_ignore("healthcheck")
    result = notify_add_log_ignore("healthcheck")
    assert "이미" in result["result"]
    cfg = json.loads(notify_config_path.read_text())
    assert cfg["log_ignore"].count("healthcheck") == 1


def test_notify_add_log_ignore_empty_pattern(notify_config_path):
    result = notify_add_log_ignore("   ")
    assert "error" in result


def test_notify_add_log_ignore_accumulates(notify_config_path):
    notify_add_log_ignore("healthcheck")
    notify_add_log_ignore("ping")
    cfg = json.loads(notify_config_path.read_text())
    assert set(cfg["log_ignore"]) == {"healthcheck", "ping"}


# ── collect_set_config ────────────────────────────────────────────────────────

def test_collect_set_config_basic(tmp_path, collector_config_path):
    folder = str(tmp_path / "metrics")
    result = collect_set_config("1h", "30d", folder)
    assert "result" in result
    assert "1.0h" in result["result"] or "60.0m" in result["result"] or "1h" in result["result"]
    cfg_data = json.loads(collector_config_path.read_text())
    assert cfg_data["interval_days"] == pytest.approx(1 / 24)
    assert cfg_data["retention_days"] == pytest.approx(30.0)


def test_collect_set_config_invalid_interval(tmp_path, collector_config_path):
    folder = str(tmp_path / "metrics")
    result = collect_set_config("notaduration", "30d", folder)
    assert "error" in result


def test_collect_set_config_zero_interval(tmp_path, collector_config_path):
    folder = str(tmp_path / "metrics")
    result = collect_set_config("0d", "30d", folder)
    assert "error" in result


def test_collect_set_config_creates_folder(tmp_path, collector_config_path):
    folder = str(tmp_path / "nested" / "metrics")
    result = collect_set_config("1h", "7d", folder)
    assert "result" in result
    assert Path(folder).exists()
