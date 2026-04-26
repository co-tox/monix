from __future__ import annotations

import dataclasses
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


CONFIG_PATH = Path.home() / ".monix" / "collector.json"
METRICS_FILENAME = "metrics.jsonl"


@dataclasses.dataclass
class CollectorConfig:
    interval_days: float
    retention_days: float
    folder: str


def load_config() -> CollectorConfig | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        d = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return CollectorConfig(
            interval_days=float(d["interval_days"]),
            retention_days=float(d["retention_days"]),
            folder=str(d["folder"]),
        )
    except Exception:
        return None


def save_config(cfg: CollectorConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(dataclasses.asdict(cfg), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def collect_and_save(folder: str) -> str:
    """메트릭을 수집해 JSONL 파일에 append. 저장된 파일 경로를 반환."""
    from monix.tools.system import (
        cpu_usage_percent,
        disk_info,
        disk_io,
        load_average,
        memory_info,
        network_io,
        swap_info,
    )

    results: dict = {}

    def _net() -> None:
        results["network"] = network_io()

    def _io() -> None:
        results["disk_io"] = disk_io()

    t1 = threading.Thread(target=_net, daemon=True)
    t2 = threading.Thread(target=_io, daemon=True)
    t1.start()
    t2.start()
    cpu = cpu_usage_percent()
    load = load_average()
    mem = memory_info()
    disks = disk_info()
    swap = swap_info()
    t1.join(timeout=3)
    t2.join(timeout=3)

    data = {
        "timestamp": datetime.now().isoformat(),
        "cpu_percent": cpu,
        "load_average": load,
        "memory": mem,
        "disks": disks,
        "swap": swap,
        "network": results.get("network", []),
        "disk_io": results.get("disk_io", []),
    }

    out_dir = Path(folder)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = metrics_path(folder)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str))
        f.write("\n")
    return str(out_path)


def load_history(folder: str, start: datetime, end: datetime) -> list[dict]:
    """주어진 기간의 JSONL 수집 이력을 시간순으로 로드."""
    result = []
    for data, ts in _iter_metric_records(metrics_path(folder)):
        if start <= ts <= end:
            data["_ts"] = ts
            result.append(data)
    result.sort(key=lambda item: item["_ts"])
    return result


def prune_metrics_file(folder: str, retention_days: float) -> int:
    """보존 기간이 지난 JSONL 샘플을 제거. 제거된 샘플 수를 반환."""
    path = metrics_path(folder)
    if not path.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    kept: list[dict] = []
    for data, ts in _iter_metric_records(path):
        if ts < cutoff:
            removed += 1
        else:
            kept.append(data)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for data in kept:
            data.pop("_ts", None)
            f.write(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str))
            f.write("\n")
    tmp_path.replace(path)
    return removed


def metrics_path(folder: str) -> Path:
    return Path(folder) / METRICS_FILENAME


def _iter_metric_records(path: Path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            ts = _record_timestamp(data)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        yield data, ts


def _record_timestamp(data: dict) -> datetime:
    raw = str(data.get("timestamp") or "")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is not None:
        ts = ts.astimezone().replace(tzinfo=None)
    return ts
