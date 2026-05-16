from __future__ import annotations

from unittest.mock import patch

from monix.tools.notify import AlertFilter, NotifyConfig, filter_alerts, send_alert
from monix.tools.notify.discord import build_discord_payload, _alert_label
from monix.tools.notify.slack import build_slack_payload


# ---------------------------------------------------------------------------
# filter_alerts
# ---------------------------------------------------------------------------

def test_filter_alerts_all_enabled():
    alerts = [
        "CPU usage is high: 90% >= 85%",
        "Memory usage is high: 88% >= 85%",
        "Disk usage is high on /: 95% >= 90%",
    ]
    assert filter_alerts(alerts, AlertFilter()) == alerts


def test_filter_alerts_cpu_disabled():
    alerts = [
        "CPU usage is high: 90% >= 85%",
        "Memory usage is high: 88% >= 85%",
    ]
    result = filter_alerts(alerts, AlertFilter(cpu=False))
    assert result == ["Memory usage is high: 88% >= 85%"]


def test_filter_alerts_memory_disabled():
    alerts = [
        "CPU usage is high: 90% >= 85%",
        "Memory usage is high: 88% >= 85%",
        "Disk usage is high on /: 95% >= 90%",
    ]
    result = filter_alerts(alerts, AlertFilter(memory=False))
    assert "Memory usage is high: 88% >= 85%" not in result
    assert len(result) == 2


def test_filter_alerts_disk_disabled():
    alerts = ["Disk usage is high on /: 95% >= 90%"]
    assert filter_alerts(alerts, AlertFilter(disk=False)) == []


def test_filter_alerts_all_disabled():
    alerts = [
        "CPU usage is high: 90% >= 85%",
        "Memory usage is high: 88% >= 85%",
        "Disk usage is high on /: 95% >= 90%",
    ]
    result = filter_alerts(alerts, AlertFilter(cpu=False, memory=False, disk=False))
    assert result == []


def test_filter_alerts_unknown_alert_passes_through():
    unknown = "Some other alert message"
    result = filter_alerts([unknown], AlertFilter(cpu=False, memory=False, disk=False))
    assert result == [unknown]


# ---------------------------------------------------------------------------
# Discord payload
# ---------------------------------------------------------------------------

def test_build_discord_payload_single_alert_color():
    payload = build_discord_payload(["CPU usage is high: 90% >= 85%"], "srv-1")
    embed = payload["embeds"][0]
    assert embed["color"] == 0xFF8C00
    assert "srv-1" in embed["title"]
    assert len(embed["fields"]) == 1


def test_build_discord_payload_multiple_alerts_color():
    alerts = ["CPU usage is high: 90% >= 85%", "Memory usage is high: 88% >= 85%"]
    payload = build_discord_payload(alerts, "srv-1")
    assert payload["embeds"][0]["color"] == 0xFF0000
    assert len(payload["embeds"][0]["fields"]) == 2


def test_alert_label():
    assert _alert_label("CPU usage is high") == "CPU"
    assert _alert_label("Memory usage is high") == "Memory"
    assert _alert_label("Disk usage is high on /") == "Disk"
    assert _alert_label("Something unknown") == "Alert"


# ---------------------------------------------------------------------------
# Slack payload
# ---------------------------------------------------------------------------

def test_build_slack_payload_structure():
    alerts = ["CPU usage is high: 90% >= 85%"]
    payload = build_slack_payload(alerts, "srv-1")
    block_types = [b["type"] for b in payload["blocks"]]
    assert block_types == ["header", "section", "context"]
    assert "srv-1" in payload["blocks"][0]["text"]["text"]
    assert "CPU usage is high" in payload["blocks"][1]["text"]["text"]


# ---------------------------------------------------------------------------
# send_alert
# ---------------------------------------------------------------------------

def test_send_alert_calls_post_json_for_discord(tmp_path):
    state = str(tmp_path / "state.json")
    config = NotifyConfig(
        discord_url="https://discord.example/webhook",
        state_path=state,
        cooldown_seconds=0,
    )
    with patch("monix.tools.notify._post_json") as mock_post:
        failed = send_alert(["CPU usage is high: 91% >= 85%"], "srv-1", config)
    mock_post.assert_called_once()
    assert failed == []


def test_send_alert_calls_post_json_for_both(tmp_path):
    state = str(tmp_path / "state.json")
    config = NotifyConfig(
        discord_url="https://discord.example/webhook",
        slack_url="https://slack.example/webhook",
        state_path=state,
        cooldown_seconds=0,
    )
    with patch("monix.tools.notify._post_json") as mock_post:
        failed = send_alert(["CPU usage is high: 91% >= 85%"], "srv-1", config)
    assert mock_post.call_count == 2
    assert failed == []


def test_send_alert_skips_on_cooldown(tmp_path):
    state = str(tmp_path / "state.json")
    config = NotifyConfig(
        discord_url="https://discord.example/webhook",
        state_path=state,
        cooldown_seconds=3600,
    )
    alerts = ["CPU usage is high: 91% >= 85%"]
    with patch("monix.tools.notify._post_json"):
        send_alert(alerts, "srv-1", config)

    with patch("monix.tools.notify._post_json") as mock_post:
        send_alert(alerts, "srv-1", config)
    mock_post.assert_not_called()


def test_send_alert_returns_failed_on_error(tmp_path):
    state = str(tmp_path / "state.json")
    config = NotifyConfig(
        discord_url="https://discord.example/webhook",
        state_path=state,
        cooldown_seconds=0,
    )
    with patch("monix.tools.notify.webhook._post_json", side_effect=OSError("timeout")):
        failed = send_alert(["CPU usage is high: 91% >= 85%"], "srv-1", config)
    assert failed == ["discord"]


def test_send_alert_no_urls_returns_empty(tmp_path):
    state = str(tmp_path / "state.json")
    config = NotifyConfig(state_path=state, cooldown_seconds=0)
    with patch("monix.tools.notify._post_json") as mock_post:
        failed = send_alert(["CPU usage is high: 91% >= 85%"], "srv-1", config)
    mock_post.assert_not_called()
    assert failed == []


def test_send_alert_filters_before_sending(tmp_path):
    state = str(tmp_path / "state.json")
    config = NotifyConfig(
        discord_url="https://discord.example/webhook",
        state_path=state,
        cooldown_seconds=0,
        alert_filter=AlertFilter(cpu=False),
    )
    alerts = ["CPU usage is high: 91% >= 85%"]
    with patch("monix.tools.notify._post_json") as mock_post:
        failed = send_alert(alerts, "srv-1", config)
    mock_post.assert_not_called()
    assert failed == []
