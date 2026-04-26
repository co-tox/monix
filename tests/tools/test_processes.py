from unittest.mock import MagicMock, patch

from monix.tools.system.processes import parse_ps, top_processes


def test_parse_ps_normal():
    output = "PID PPID %CPU %MEM COMMAND\n1234 1 10.5 2.3 python3\n5678 1 5.0 1.1 bash"
    result = parse_ps(output, limit=10)
    assert len(result) == 2
    assert result[0]["cpu"] == 10.5
    assert result[0]["pid"] == 1234
    assert result[0]["command"] == "python3"


def test_parse_ps_sorted_by_cpu():
    output = "PID PPID %CPU %MEM COMMAND\n1 0 1.0 0.1 low\n2 0 9.9 0.2 high\n3 0 5.5 0.3 mid"
    result = parse_ps(output, limit=10)
    assert result[0]["cpu"] == 9.9
    assert result[1]["cpu"] == 5.5
    assert result[2]["cpu"] == 1.0


def test_parse_ps_limit():
    lines = ["PID PPID %CPU %MEM COMMAND"] + [f"{i} 0 {i}.0 0.1 cmd{i}" for i in range(1, 6)]
    result = parse_ps("\n".join(lines), limit=3)
    assert len(result) == 3


def test_parse_ps_empty_output():
    result = parse_ps("PID PPID %CPU %MEM COMMAND\n", limit=10)
    assert result == []


def test_parse_ps_skips_malformed_lines():
    output = "PID PPID %CPU %MEM COMMAND\nbad line\n1 0 1.0 0.1 ok"
    result = parse_ps(output, limit=10)
    assert len(result) == 1
    assert result[0]["command"] == "ok"


def test_top_processes_returns_list():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "PID PPID %CPU %MEM COMMAND\n1 0 1.0 0.5 init"
    with patch("monix.tools.system.processes.subprocess.run", return_value=mock_result):
        result = top_processes(limit=5)
    assert isinstance(result, list)


def test_top_processes_subprocess_failure_returns_empty():
    import subprocess
    with patch("monix.tools.system.processes.subprocess.run", side_effect=OSError("fail")):
        result = top_processes()
    assert result == []
