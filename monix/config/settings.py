from __future__ import annotations

import dataclasses
import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """현재 디렉토리의 .env 파일을 읽어 os.environ에 주입 (이미 설정된 값은 덮어쓰지 않음)."""
    dotenv = Path(path)
    if not dotenv.is_file():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


@dataclasses.dataclass(frozen=True)
class Thresholds:
    cpu_warn: float = 85.0
    mem_warn: float = 85.0
    disk_warn: float = 90.0

    @classmethod
    def from_env(cls) -> "Thresholds":
        return cls(
            cpu_warn=_env_float("MONIX_CPU_WARN", 85.0),
            mem_warn=_env_float("MONIX_MEM_WARN", 85.0),
            disk_warn=_env_float("MONIX_DISK_WARN", 90.0),
        )


@dataclasses.dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    model: str
    log_file: str
    thresholds: Thresholds
    platform: str  # "linux" | "darwin" — MONIX_PLATFORM으로 override 가능

    @classmethod
    def from_env(cls) -> "Settings":
        import platform as _platform
        from monix.config.keystore import load_api_key
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY") or load_api_key(),
            model=os.getenv("MONIX_MODEL", "gemini-2.5-flash"),
            log_file=default_log_file(),
            thresholds=Thresholds.from_env(),
            platform=_resolve_platform(os.getenv("MONIX_PLATFORM", _platform.system())),
        )

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)


def _resolve_platform(value: str) -> str:
    normalized = value.lower()
    return "mac" if normalized == "darwin" else normalized


def default_log_file() -> str:
    env_path = os.getenv("MONIX_LOG_FILE")
    if env_path:
        return env_path
    for path in ("/var/log/syslog", "/var/log/messages", "/var/log/system.log"):
        if Path(path).exists():
            return path
    return "/var/log/syslog"


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
