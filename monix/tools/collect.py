from __future__ import annotations

import dataclasses
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


CONFIG_PATH = Path.home() / ".monix" / "collector.json"


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
    """메트릭을 수집해 JSON 파일로 저장. 저장된 파일 경로를 반환."""
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
    filename = datetime.now().strftime("monix_%Y-%m-%d_%H-%M-%S.json")
    out_path = out_dir / filename
    out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return str(out_path)


def load_history(folder: str, start: datetime, end: datetime) -> list[dict]:
    """주어진 기간의 수집 파일을 시간순으로 로드."""
    result = []
    for f in sorted(Path(folder).glob("monix_*.json")):
        try:
            ts = datetime.strptime(f.stem[len("monix_"):], "%Y-%m-%d_%H-%M-%S")
            if start <= ts <= end:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_ts"] = ts
                result.append(data)
        except Exception:
            pass
    return result


def purge_old_files(folder: str, retention_days: float) -> int:
    """보존 기간이 지난 파일 삭제. 삭제된 파일 수를 반환."""
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for f in Path(folder).glob("monix_*.json"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed
