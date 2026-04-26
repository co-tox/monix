"""Tests for /docker CLI command dispatch."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from monix.cli import dispatch


# --- /docker (no subcommand) ---

def test_docker_no_args_shows_help():
    result = dispatch("/docker")
    assert "Docker 명령어" in result
    assert "/docker ps" in result


# --- /docker ps / list ---

def test_docker_ps_renders_containers():
    fake = [
        {"name": "web", "status": "Up 2 hours", "image": "nginx:latest"},
        {"name": "db", "status": "Up 1 day", "image": "postgres:15"},
    ]
    with patch("monix.cli.list_containers", return_value=fake):
        result = dispatch("/docker ps")
    assert "web" in result
    assert "db" in result
    assert "nginx:latest" in result


def test_docker_list_alias():
    fake = [{"name": "app", "status": "Up", "image": "myimage:1"}]
    with patch("monix.cli.list_containers", return_value=fake):
        result = dispatch("/docker list")
    assert "app" in result


def test_docker_ps_no_containers():
    with patch("monix.cli.list_containers", return_value=[]):
        result = dispatch("/docker ps")
    assert "없습니다" in result or "No running" in result


# --- /docker logs ---

def test_docker_logs_ok():
    fake_output = "INFO: started\nERROR: oops"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_output):
        result = dispatch("/docker logs myapp")
    assert "Log:" in result
    assert "myapp" in result


def test_docker_logs_missing_container_arg():
    result = dispatch("/docker logs")
    assert "사용법" in result


def test_docker_logs_respects_n():
    captured = {}

    def fake_check_output(cmd, **kwargs):
        captured["tail_arg"] = int(cmd[cmd.index("--tail") + 1])
        return "line"

    with patch("monix.tools.logs.docker.containers.subprocess.check_output", side_effect=fake_check_output):
        dispatch("/docker logs myapp -n 50")
    assert captured["tail_arg"] == 50


# --- /docker search ---

def test_docker_search_no_pattern_returns_errors():
    fake_log = "INFO: ok\nERROR: crash\nDEBUG: fine"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = dispatch("/docker search myapp")
    assert "에러/경고" in result
    assert "crash" in result


def test_docker_search_with_pattern():
    fake_log = "INFO: connected\nERROR: timeout\nINFO: retry"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = dispatch('/docker search myapp timeout')
    assert "timeout" in result


def test_docker_search_missing_container_arg():
    result = dispatch("/docker search")
    assert "사용법" in result


def test_docker_search_container_error():
    exc = subprocess.CalledProcessError(1, "docker", output="No such container: ghost")
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", side_effect=exc):
        result = dispatch("/docker search ghost")
    assert "ghost" in result


# --- /docker live (streaming — mocked) ---

def test_docker_live_missing_container_arg():
    result = dispatch("/docker live")
    assert "사용법" in result


def test_docker_live_streams_then_stops(capsys):
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["line1\n", "line2\n"])
    with patch("monix.tools.logs.docker.containers.subprocess.Popen", return_value=mock_proc):
        with patch("monix.tools.logs.docker.containers._pipe_ready", return_value=True):
            result = dispatch("/docker live myapp")
    out = capsys.readouterr().out
    assert "line1" in out
    assert "line2" in out
    assert "종료" in result


# --- /docker unknown subcommand ---

def test_docker_unknown_subcommand_shows_help():
    result = dispatch("/docker frobnicate")
    assert "Docker 명령어" in result
