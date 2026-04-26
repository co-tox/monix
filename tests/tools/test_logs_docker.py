import subprocess
from unittest.mock import MagicMock, patch

from monix.tools.logs.docker import follow_container, list_containers, tail_container


# --- tail_container ---

def test_tail_container_ok():
    with patch("monix.tools.logs.docker.subprocess.check_output", return_value="log line 1\nlog line 2"):
        result = tail_container("myapp")
    assert result["status"] == "ok"
    assert result["path"] == "docker://myapp"
    assert "log line 1" in result["lines"]


def test_tail_container_docker_not_found():
    with patch("monix.tools.logs.docker.subprocess.check_output", side_effect=FileNotFoundError):
        result = tail_container("myapp")
    assert result["status"] == "error"
    assert any("docker" in l for l in result["lines"])


def test_tail_container_timeout():
    with patch(
        "monix.tools.logs.docker.subprocess.check_output",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=10),
    ):
        result = tail_container("myapp")
    assert result["status"] == "error"
    assert any("타임아웃" in l for l in result["lines"])


def test_tail_container_called_process_error():
    exc = subprocess.CalledProcessError(1, "docker", output="No such container: myapp")
    with patch("monix.tools.logs.docker.subprocess.check_output", side_effect=exc):
        result = tail_container("myapp")
    assert result["status"] == "error"
    assert any("No such container" in l for l in result["lines"])


def test_tail_container_os_error():
    with patch("monix.tools.logs.docker.subprocess.check_output", side_effect=OSError("permission denied")):
        result = tail_container("myapp")
    assert result["status"] == "error"


# --- follow_container ---

def test_follow_container_yields_lines():
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["line1\n", "line2\n"])
    with patch("monix.tools.logs.docker.subprocess.Popen", return_value=mock_proc):
        lines = list(follow_container("myapp", initial_lines=2))
    assert lines == ["line1", "line2"]
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()


def test_follow_container_terminates_on_exhaustion():
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    with patch("monix.tools.logs.docker.subprocess.Popen", return_value=mock_proc):
        list(follow_container("myapp"))
    mock_proc.terminate.assert_called_once()


# --- list_containers ---

def test_list_containers_parses_output():
    fake_output = "web\tUp 2 hours\tnginx:latest\ndb\tUp 1 day\tpostgres:15"
    with patch("monix.tools.logs.docker.subprocess.check_output", return_value=fake_output):
        result = list_containers()
    assert len(result) == 2
    assert result[0] == {"name": "web", "status": "Up 2 hours", "image": "nginx:latest"}
    assert result[1]["name"] == "db"


def test_list_containers_empty_output():
    with patch("monix.tools.logs.docker.subprocess.check_output", return_value=""):
        result = list_containers()
    assert result == []


def test_list_containers_docker_unavailable():
    with patch("monix.tools.logs.docker.subprocess.check_output", side_effect=FileNotFoundError):
        result = list_containers()
    assert result == []


def test_list_containers_skips_malformed_lines():
    fake_output = "web\tUp 2 hours\tnginx\nmalformed_line"
    with patch("monix.tools.logs.docker.subprocess.check_output", return_value=fake_output):
        result = list_containers()
    assert len(result) == 1
    assert result[0]["name"] == "web"
