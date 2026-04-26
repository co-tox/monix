from monix.config import Thresholds
from monix.core.assistant import infer_service_name, local_answer
from monix.render import render_snapshot
from monix.tools.system import build_alerts, human_bytes, human_duration


def test_human_bytes():
    assert human_bytes(None) == "unknown"
    assert human_bytes(1024) == "1.0 KiB"


def test_human_duration():
    assert human_duration(None) == "unknown"
    assert human_duration(90061) == "1d 1h 1m"


def test_build_alerts():
    snapshot = {
        "cpu_percent": 91.0,
        "memory": {"percent": 88.0},
        "disks": [{"path": "/", "percent": 95.0}],
    }
    alerts = build_alerts(snapshot, Thresholds(cpu_warn=90, mem_warn=85, disk_warn=90))
    assert len(alerts) == 3


def test_render_snapshot_minimal():
    snapshot = {
        "host": "app-1",
        "os": "Linux",
        "time": "2026-04-26 00:00:00 KST",
        "uptime": "1d",
        "cpu_percent": 12.5,
        "load_average": (0.1, 0.2, 0.3),
        "memory": {"percent": 30, "available": 1024},
        "disks": [{"path": "/", "percent": 40, "free": 2048, "total": 4096}],
        "alerts": [],
        "top_processes": [],
    }
    rendered = render_snapshot(snapshot)
    assert "Host: app-1" in rendered
    assert "Alerts:" in rendered


def test_local_answer_cpu():
    snapshot = {
        "cpu_percent": 10.0,
        "load_average": (0.1, 0.2, 0.3),
        "top_processes": [{"pid": 1, "ppid": 0, "cpu": 1.0, "mem": 0.1, "command": "init"}],
    }
    assert "CPU 사용률" in local_answer("cpu 상태", snapshot)


def test_infer_service_name():
    assert infer_service_name(["nginx", "서비스", "확인"]) == "nginx"
