from unittest.mock import MagicMock, patch

import pytest

from monix.tools.system import (
    build_alerts,
    collect_snapshot,
    disk_info,
    human_bytes,
    human_duration,
    memory_info,
    top_processes,
)
from monix.tools.system.metrics import load_average, uptime_seconds_value
from monix.config import Settings, Thresholds


# ---------------------------------------------------------------------------
# human_bytes
# ---------------------------------------------------------------------------

def test_human_bytes_none():
    assert human_bytes(None) == "unknown"


def test_human_bytes_bytes():
    assert human_bytes(512) == "512.0 B"


def test_human_bytes_kib():
    assert human_bytes(1024) == "1.0 KiB"


def test_human_bytes_mib():
    assert human_bytes(1024 ** 2) == "1.0 MiB"


def test_human_bytes_gib():
    assert human_bytes(1024 ** 3) == "1.0 GiB"


def test_human_bytes_tib():
    assert human_bytes(1024 ** 4) == "1.0 TiB"


# ---------------------------------------------------------------------------
# human_duration
# ---------------------------------------------------------------------------

def test_human_duration_none():
    assert human_duration(None) == "unknown"


def test_human_duration_minutes_only():
    assert human_duration(300) == "5m"


def test_human_duration_hours_minutes():
    assert human_duration(3661) == "1h 1m"


def test_human_duration_days():
    assert human_duration(90061) == "1d 1h 1m"


def test_human_duration_zero():
    assert human_duration(0) == "0m"


def test_human_duration_exactly_one_day():
    assert human_duration(86400) == "1d 0m"


# ---------------------------------------------------------------------------
# build_alerts
# ---------------------------------------------------------------------------

def _thresholds(cpu=80, mem=80, disk=90):
    return Thresholds(cpu_warn=cpu, mem_warn=mem, disk_warn=disk)


def test_build_alerts_no_alerts():
    snapshot = {"cpu_percent": 50.0, "memory": {"percent": 60.0}, "disks": []}
    assert build_alerts(snapshot, _thresholds()) == []


def test_build_alerts_cpu_high():
    snapshot = {"cpu_percent": 85.0, "memory": {"percent": 50.0}, "disks": []}
    alerts = build_alerts(snapshot, _thresholds(cpu=80))
    assert any("CPU" in a for a in alerts)


def test_build_alerts_mem_high():
    snapshot = {"cpu_percent": 10.0, "memory": {"percent": 95.0}, "disks": []}
    alerts = build_alerts(snapshot, _thresholds(mem=80))
    assert any("Memory" in a for a in alerts)


def test_build_alerts_disk_high():
    snapshot = {
        "cpu_percent": 10.0,
        "memory": {"percent": 50.0},
        "disks": [{"path": "/", "percent": 92.0}],
    }
    alerts = build_alerts(snapshot, _thresholds(disk=90))
    assert any("Disk" in a for a in alerts)


def test_build_alerts_none_values_skipped():
    snapshot = {"cpu_percent": None, "memory": {"percent": None}, "disks": [{"path": "/", "percent": None}]}
    assert build_alerts(snapshot, _thresholds()) == []


def test_build_alerts_missing_keys():
    snapshot = {}
    assert build_alerts(snapshot, _thresholds()) == []


# ---------------------------------------------------------------------------
# disk_info
# ---------------------------------------------------------------------------

def test_disk_info_returns_list():
    result = disk_info()
    assert isinstance(result, list)


def test_disk_info_root_entry():
    result = disk_info(("/",))
    assert len(result) == 1
    entry = result[0]
    assert entry["path"] == "/"
    assert isinstance(entry["total"], int)
    assert isinstance(entry["used"], int)
    assert isinstance(entry["free"], int)
    assert entry["percent"] is None or isinstance(entry["percent"], float)


def test_disk_info_missing_path_skipped():
    result = disk_info(("/nonexistent_path_xyz",))
    assert result == []


def test_disk_info_multiple_paths():
    result = disk_info(("/", "/tmp"))
    assert len(result) <= 2


# ---------------------------------------------------------------------------
# load_average
# ---------------------------------------------------------------------------

def test_load_average_returns_tuple_or_none():
    result = load_average()
    assert result is None or (isinstance(result, tuple) and len(result) == 3)


def test_load_average_values_are_floats():
    result = load_average()
    if result is not None:
        assert all(isinstance(v, float) for v in result)


def test_load_average_oserror_returns_none():
    with patch("monix.tools.system.metrics.os.getloadavg", side_effect=OSError):
        result = load_average()
    assert result is None


# ---------------------------------------------------------------------------
# memory_info
# ---------------------------------------------------------------------------

def test_memory_info_returns_dict():
    result = memory_info()
    assert isinstance(result, dict)


def test_memory_info_has_required_keys():
    result = memory_info()
    for key in ("total", "available", "used", "percent"):
        assert key in result


# ---------------------------------------------------------------------------
# uptime_seconds_value
# ---------------------------------------------------------------------------

def test_uptime_seconds_returns_int_or_none():
    result = uptime_seconds_value()
    assert result is None or isinstance(result, int)


def test_uptime_seconds_positive_or_none():
    result = uptime_seconds_value()
    if result is not None:
        assert result >= 0


# ---------------------------------------------------------------------------
# collect_snapshot
# ---------------------------------------------------------------------------

def test_collect_snapshot_returns_dict():
    result = collect_snapshot()
    assert isinstance(result, dict)


def test_collect_snapshot_required_keys():
    result = collect_snapshot()
    for key in ("host", "os", "time", "uptime", "load_average", "cpu_percent",
                "memory", "disks", "top_processes", "alerts"):
        assert key in result


def test_collect_snapshot_alerts_is_list():
    result = collect_snapshot()
    assert isinstance(result["alerts"], list)


def test_collect_snapshot_disks_is_list():
    result = collect_snapshot()
    assert isinstance(result["disks"], list)


def test_collect_snapshot_top_processes_is_list():
    result = collect_snapshot()
    assert isinstance(result["top_processes"], list)


def test_collect_snapshot_respects_thresholds():
    import dataclasses
    base = Settings.from_env()
    settings = dataclasses.replace(base, thresholds=Thresholds(cpu_warn=0.0, mem_warn=0.0, disk_warn=0.0))
    result = collect_snapshot(settings)
    assert isinstance(result["alerts"], list)


# ---------------------------------------------------------------------------
# Import path correctness
# ---------------------------------------------------------------------------

def test_top_processes_importable_from_system():
    from monix.tools.system import top_processes
    assert callable(top_processes)


def test_top_processes_importable_from_system_processes():
    from monix.tools.system.processes import top_processes, parse_ps
    assert callable(top_processes)
    assert callable(parse_ps)
