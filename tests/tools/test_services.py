from unittest.mock import patch

from monix.tools.services import service_status


def test_service_status_empty_name():
    result = service_status("   ")
    assert result["status"] == "unknown"
    assert "empty" in result["details"]


def test_service_status_no_systemctl():
    with patch("monix.tools.services.shutil.which", return_value=None):
        result = service_status("nginx")
    assert result["name"] == "nginx"
    assert result["status"] == "unknown"
    assert "systemctl" in result["details"]


def test_service_status_ok():
    with patch("monix.tools.services.shutil.which", return_value="/bin/systemctl"), \
         patch("monix.tools.services.subprocess.check_output", return_value="Active: active (running)"):
        result = service_status("nginx")
    assert result["name"] == "nginx"
    assert result["status"] == "ok"
    assert "Active" in result["details"]


def test_service_status_error_from_systemctl():
    import subprocess
    exc = subprocess.CalledProcessError(1, "systemctl", output="Unit nginx.service not found.")
    with patch("monix.tools.services.shutil.which", return_value="/bin/systemctl"), \
         patch("monix.tools.services.subprocess.check_output", side_effect=exc):
        result = service_status("nginx")
    assert result["status"] == "error"
    assert "not found" in result["details"]


def test_service_status_strips_whitespace():
    with patch("monix.tools.services.shutil.which", return_value=None):
        result = service_status("  sshd  ")
    assert result["name"] == "sshd"
