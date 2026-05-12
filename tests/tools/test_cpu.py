from unittest.mock import patch

from monix.tools.system.cpu import cpu_core_usage_percents


def test_cpu_core_usage_linux_reads_per_core_proc_stat():
    first = "\n".join([
        "cpu  100 0 100 800 0 0 0 0 0 0",
        "cpu0 50 0 50 400 0 0 0 0 0 0",
        "cpu1 50 0 50 400 0 0 0 0 0 0",
    ])
    second = "\n".join([
        "cpu  200 0 200 1600 0 0 0 0 0 0",
        "cpu0 100 0 100 800 0 0 0 0 0 0",
        "cpu1 50 0 150 700 0 0 0 0 0 0",
    ])
    with patch("monix.tools.system.cpu.Path.read_text", side_effect=[first, second]), patch("monix.tools.system.cpu.time.sleep"):
        assert cpu_core_usage_percents(is_linux=True, sample_seconds=0) == [20.0, 25.0]


def test_cpu_core_usage_linux_returns_empty_when_proc_stat_missing():
    with patch("monix.tools.system.cpu.Path.read_text", side_effect=OSError):
        assert cpu_core_usage_percents(is_linux=True, sample_seconds=0) == []
