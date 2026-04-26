"""Tests for /docker CLI command dispatch."""
import subprocess
from unittest.mock import MagicMock, patch

from monix.cli import dispatch


# --- /docker (no subcommand) ---

def test_docker_no_args_shows_help():
    result = dispatch("/docker")
    assert "Docker commands" in result
    assert "/docker ps" in result


# --- /docker ps ---

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


def test_docker_ps_no_containers():
    with patch("monix.cli.list_containers", return_value=[]):
        result = dispatch("/docker ps")
    assert "실행 중인 컨테이너 없음" in result


# --- /docker add ---

def test_docker_add_registers_alias():
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.add.return_value = (MagicMock(), True)
        result = dispatch("/docker add @myapp myapp")
    assert "Registered" in result
    assert "myapp" in result


def test_docker_add_update_existing():
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.add.return_value = (MagicMock(), False)
        result = dispatch("/docker add @myapp myapp")
    assert "Updated" in result


def test_docker_add_uses_alias_as_container_when_omitted():
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.add.return_value = (MagicMock(), True)
        dispatch("/docker add @myapp")
    mock_reg.add.assert_called_once_with("myapp", "docker", container="myapp")


def test_docker_add_missing_alias():
    result = dispatch("/docker add")
    assert "Usage" in result


# --- /docker list ---

def test_docker_list_shows_registered_aliases():
    fake_entry = MagicMock()
    fake_entry.alias = "myapp"
    fake_entry.type = "docker"
    fake_entry.container = "myapp"
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.load.return_value = [fake_entry]
        result = dispatch("/docker list")
    assert "myapp" in result


def test_docker_list_empty():
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.load.return_value = []
        result = dispatch("/docker list")
    assert "등록된 Docker 컨테이너가 없습니다." in result


# --- /docker @alias ---

def _make_docker_entry(alias: str, container: str):
    e = MagicMock()
    e.alias = alias
    e.type = "docker"
    e.container = container
    return e


def test_docker_alias_view():
    entry = _make_docker_entry("web", "web")
    fake_result = {"path": "docker://web", "status": "ok", "lines": ["INFO: started"]}
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        with patch("monix.cli.tail_container", return_value=fake_result):
            result = dispatch("/docker @web")
    assert "started" in result or "docker://web" in result


def test_docker_alias_not_found():
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = None
        result = dispatch("/docker @ghost")
    assert "ghost" in result
    assert "not registered" in result


def test_docker_alias_wrong_type():
    entry = MagicMock()
    entry.type = "nginx"
    entry.alias = "mynginx"
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        result = dispatch("/docker @mynginx")
    assert "nginx" in result


def test_docker_alias_search():
    entry = _make_docker_entry("web", "web")
    fake_result = {
        "path": "docker://web", "status": "ok", "query": "error",
        "total_scanned": 10, "matches": [],
    }
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        with patch("monix.cli.search_container", return_value=fake_result):
            result = dispatch("/docker @web --search error")
    assert "web" in result


def test_docker_alias_live(capsys):
    entry = _make_docker_entry("web", "web")
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["log1\n", "log2\n"])
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        with patch("monix.tools.logs.docker.containers.subprocess.Popen", return_value=mock_proc):
            with patch("monix.tools.logs.docker.containers._pipe_ready", return_value=True):
                result = dispatch("/docker @web --live")
    out = capsys.readouterr().out
    assert "log1" in out
    assert "Stopped" in result


# --- /docker remove ---

def test_docker_remove_ok():
    entry = _make_docker_entry("web", "web")
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        mock_reg.remove.return_value = True
        result = dispatch("/docker remove @web")
    assert "removed" in result


def test_docker_remove_not_found():
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = None
        mock_reg.remove.return_value = False
        result = dispatch("/docker remove @ghost")
    assert "ghost" in result


def test_docker_remove_wrong_type():
    entry = MagicMock()
    entry.type = "app"
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        result = dispatch("/docker remove @myapp")
    assert "docker" in result or "log remove" in result


def test_docker_remove_missing_alias():
    result = dispatch("/docker remove")
    assert "Usage" in result


# --- /docker logs|search|live with @alias ---

def test_docker_logs_alias_resolves():
    entry = _make_docker_entry("web", "mycontainer")
    fake_output = "INFO: ok"
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_output):
            result = dispatch("/docker logs @web")
    assert "mycontainer" in result or "ok" in result


def test_docker_logs_alias_not_found():
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = None
        result = dispatch("/docker logs @ghost")
    assert "ghost" in result
    assert "not registered" in result


def test_docker_search_alias_resolves():
    entry = _make_docker_entry("api", "api-container")
    fake_log = "ERROR: crash"
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
            result = dispatch("/docker search @api")
    assert "crash" in result


def test_docker_live_alias_resolves(capsys):
    entry = _make_docker_entry("api", "api-container")
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["stream\n"])
    with patch("monix.cli.registry") as mock_reg:
        mock_reg.get.return_value = entry
        with patch("monix.tools.logs.docker.containers.subprocess.Popen", return_value=mock_proc):
            with patch("monix.tools.logs.docker.containers._pipe_ready", return_value=True):
                result = dispatch("/docker live @api")
    out = capsys.readouterr().out
    assert "stream" in out
    assert "Stopped" in result


# --- /docker logs ---

def test_docker_logs_ok():
    fake_output = "INFO: started\nERROR: oops"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_output):
        result = dispatch("/docker logs myapp")
    assert "docker://myapp" in result
    assert "myapp" in result


def test_docker_logs_missing_container_arg():
    result = dispatch("/docker logs")
    assert "Usage" in result


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
    assert "Usage" in result


def test_docker_search_container_error():
    exc = subprocess.CalledProcessError(1, "docker", output="No such container: ghost")
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", side_effect=exc):
        result = dispatch("/docker search ghost")
    assert "ghost" in result


# --- /docker live (streaming — mocked) ---

def test_docker_live_missing_container_arg():
    result = dispatch("/docker live")
    assert "Usage" in result


def test_docker_live_streams_then_stops(capsys):
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["line1\n", "line2\n"])
    with patch("monix.tools.logs.docker.containers.subprocess.Popen", return_value=mock_proc):
        with patch("monix.tools.logs.docker.containers._pipe_ready", return_value=True):
            result = dispatch("/docker live myapp")
    out = capsys.readouterr().out
    assert "line1" in out
    assert "line2" in out
    assert "Stopped" in result


# --- /docker unknown subcommand ---

def test_docker_unknown_subcommand_shows_help():
    result = dispatch("/docker frobnicate")
    assert "Docker commands" in result
