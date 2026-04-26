import json
from datetime import datetime, timedelta
from unittest.mock import patch

from monix.tools.collect import collect_and_save, load_history, metrics_path, prune_metrics_file


def test_collect_and_save_appends_to_metrics_jsonl(tmp_path):
    with (
        patch("monix.tools.system.cpu_usage_percent", return_value=12.3),
        patch("monix.tools.system.load_average", return_value=(1.0, 2.0, 3.0)),
        patch("monix.tools.system.memory_info", return_value={"percent": 45.6}),
        patch("monix.tools.system.disk_info", return_value=[{"path": "/", "percent": 70.0}]),
        patch("monix.tools.system.swap_info", return_value={"percent": 0.0}),
        patch("monix.tools.system.network_io", return_value=[]),
        patch("monix.tools.system.disk_io", return_value=[]),
    ):
        first = collect_and_save(str(tmp_path))
        second = collect_and_save(str(tmp_path))

    assert first == second
    assert first.endswith("metrics.jsonl")
    lines = metrics_path(str(tmp_path)).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["cpu_percent"] == 12.3


def test_load_history_reads_jsonl_period(tmp_path):
    now = datetime.now()
    records = [
        {"timestamp": (now - timedelta(minutes=10)).isoformat(), "cpu_percent": 1.0},
        {"timestamp": (now - timedelta(minutes=2)).isoformat(), "cpu_percent": 2.0},
        {"timestamp": now.isoformat(), "cpu_percent": 3.0},
    ]
    metrics_path(str(tmp_path)).write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    result = load_history(str(tmp_path), now - timedelta(minutes=3), now + timedelta(seconds=1))

    assert [record["cpu_percent"] for record in result] == [2.0, 3.0]
    assert all("_ts" in record for record in result)


def test_prune_metrics_file_removes_old_lines_and_skips_bad_json(tmp_path):
    now = datetime.now()
    records = [
        {"timestamp": (now - timedelta(minutes=2)).isoformat(), "cpu_percent": 1.0},
        {"timestamp": now.isoformat(), "cpu_percent": 2.0},
    ]
    metrics_path(str(tmp_path)).write_text(
        json.dumps(records[0]) + "\nnot-json\n" + json.dumps(records[1]) + "\n",
        encoding="utf-8",
    )

    removed = prune_metrics_file(str(tmp_path), retention_days=1 / 1440)

    lines = metrics_path(str(tmp_path)).read_text(encoding="utf-8").splitlines()
    assert removed == 1
    assert len(lines) == 1
    assert json.loads(lines[0])["cpu_percent"] == 2.0
