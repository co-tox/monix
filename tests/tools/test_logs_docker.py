import subprocess
from unittest.mock import MagicMock, patch

from monix.tools.logs.docker import follow_container, list_containers, search_container, tail_container


# --- tail_container ---

def test_tail_container_ok():
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value="log line 1\nlog line 2"):
        result = tail_container("myapp")
    assert result["status"] == "ok"
    assert result["path"] == "docker://myapp"
    assert "log line 1" in result["lines"]


def test_tail_container_docker_not_found():
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", side_effect=FileNotFoundError):
        result = tail_container("myapp")
    assert result["status"] == "error"
    assert any("docker" in l for l in result["lines"])


def test_tail_container_timeout():
    with patch(
        "monix.tools.logs.docker.containers.subprocess.check_output",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=10),
    ):
        result = tail_container("myapp")
    assert result["status"] == "error"
    assert any("타임아웃" in l for l in result["lines"])


def test_tail_container_called_process_error():
    exc = subprocess.CalledProcessError(1, "docker", output="No such container: myapp")
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", side_effect=exc):
        result = tail_container("myapp")
    assert result["status"] == "error"
    assert any("No such container" in l for l in result["lines"])


def test_tail_container_os_error():
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", side_effect=OSError("permission denied")):
        result = tail_container("myapp")
    assert result["status"] == "error"


# --- follow_container ---

def test_follow_container_yields_lines():
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["line1\n", "line2\n"])
    with patch("monix.tools.logs.docker.containers.subprocess.Popen", return_value=mock_proc):
        lines = list(follow_container("myapp", initial_lines=2))
    # last element is EOF sentinel (None) when container stops
    assert [l for l in lines if l is not None] == ["line1", "line2"]
    assert lines[-1] is None
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()


def test_follow_container_terminates_on_exhaustion():
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    with patch("monix.tools.logs.docker.containers.subprocess.Popen", return_value=mock_proc):
        list(follow_container("myapp"))
    mock_proc.terminate.assert_called_once()


# --- list_containers ---

def test_list_containers_parses_output():
    fake_output = "web\tUp 2 hours\tnginx:latest\ndb\tUp 1 day\tpostgres:15"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_output):
        result = list_containers()
    assert len(result) == 2
    assert result[0] == {"name": "web", "status": "Up 2 hours", "image": "nginx:latest"}
    assert result[1]["name"] == "db"


def test_list_containers_empty_output():
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=""):
        result = list_containers()
    assert result == []


def test_list_containers_docker_unavailable():
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", side_effect=FileNotFoundError):
        result = list_containers()
    assert result == []


def test_list_containers_skips_malformed_lines():
    fake_output = "web\tUp 2 hours\tnginx\nmalformed_line"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_output):
        result = list_containers()
    assert len(result) == 1
    assert result[0]["name"] == "web"


# --- search_container ---

def test_search_container_error_filter():
    fake_log = "INFO: ok\nERROR: crash\nDEBUG: fine"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = search_container("myapp")
    assert result["status"] == "ok"
    assert result["query"] is None
    assert len(result["matches"]) == 1
    assert result["matches"][0]["severity"] == "error"
    assert "crash" in result["matches"][0]["line"]


def test_search_container_pattern_match():
    fake_log = "INFO: connected\nERROR: timeout waiting for db\nINFO: retry"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = search_container("myapp", pattern="timeout")
    assert result["query"] == "timeout"
    assert len(result["matches"]) == 1
    assert "timeout" in result["matches"][0]["line"]


def test_search_container_pattern_case_insensitive():
    fake_log = "TIMEOUT\ntimeout\nTimeOut\nnope"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = search_container("myapp", pattern="timeout")
    assert len(result["matches"]) == 3


def test_search_container_invalid_regex_fallback():
    fake_log = "err[or\nok"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = search_container("myapp", pattern="err[or")
    assert result["status"] == "ok"
    assert len(result["matches"]) == 1
    assert "warning" in result


def test_search_container_total_scanned():
    fake_log = "\n".join(f"line{i}" for i in range(10))
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = search_container("myapp", pattern="line1")
    assert result["total_scanned"] == 10


def test_search_container_container_not_found():
    exc = subprocess.CalledProcessError(1, "docker", output="No such container: ghost")
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", side_effect=exc):
        result = search_container("ghost")
    assert result["status"] == "error"
    assert result["total_scanned"] == 0
    assert result["matches"] == []


def test_search_container_no_matches():
    fake_log = "INFO: all good\nDEBUG: nothing here"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = search_container("myapp")
    assert result["matches"] == []
    assert result["total_scanned"] == 2


def test_search_container_lineno_correct():
    fake_log = "line1\nline2\nERROR: line3\nline4"
    with patch("monix.tools.logs.docker.containers.subprocess.check_output", return_value=fake_log):
        result = search_container("myapp")
    assert result["matches"][0]["lineno"] == 3
