"""Tests for pick_with_filter TTY input handling in picker.py."""
from unittest.mock import MagicMock, patch

from monix.picker import pick_with_filter


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_buf(byte_seq):
    it = iter(byte_seq)

    def _read(n=1):  # noqa: ARG001
        try:
            return bytes([next(it)])
        except StopIteration:
            return b""

    mock = MagicMock(name="stdin.buffer")
    mock.read.side_effect = _read
    return mock


def _run(byte_seq):
    """Run pick_with_filter against a simulated byte sequence; return the result."""
    mock_termios = MagicMock(name="termios")
    mock_termios.tcgetattr.return_value = []
    mock_termios.TCSADRAIN = 1
    mock_tty = MagicMock(name="tty")

    with (
        patch("monix.picker.termios", mock_termios),
        patch("monix.picker.tty", mock_tty),
        patch("monix.picker._HAS_TTY", True),
        patch("sys.stdout.isatty", return_value=True),
        patch("sys.stdout.write"),
        patch("sys.stdout.flush"),
        patch("sys.stdin") as mock_stdin,
    ):
        mock_stdin.fileno.return_value = 0
        mock_stdin.buffer = _make_buf(byte_seq)
        return pick_with_filter("")


# ── Backspace in picker ────────────────────────────────────────────────────────


def test_picker_backspace_del_x7f_removes_char():
    """DEL (\\x7f) should delete the last typed character in the filter query."""
    # Type 's', 't', then delete 't' → selects /stat (starts with 's')
    result = _run([ord("s"), ord("t"), 0x7F, ord("\r")])
    assert result is not None
    assert result.startswith("/s")


def test_picker_backspace_bs_x08_removes_char():
    """BS (\\x08) from MobaXterm/PuTTY SSH should delete last character like \\x7f."""
    result = _run([ord("s"), ord("t"), 0x08, ord("\r")])
    assert result is not None
    assert result.startswith("/s")


def test_picker_backspace_bs_x08_on_empty_cancels():
    """BS (\\x08) on an empty query should cancel the picker (return None)."""
    result = _run([0x08])
    assert result is None


def test_picker_backspace_del_x7f_on_empty_cancels():
    """DEL (\\x7f) on an empty query should cancel the picker (return None)."""
    result = _run([0x7F])
    assert result is None


# ── Picker cancellation ────────────────────────────────────────────────────────


def test_picker_ctrl_c_cancels():
    result = _run([0x03])
    assert result is None


def test_picker_ctrl_d_cancels():
    result = _run([0x04])
    assert result is None


# ── Picker selection ───────────────────────────────────────────────────────────


def test_picker_enter_selects_first_item():
    result = _run([ord("\r")])
    assert result is not None


def test_picker_filter_then_select():
    # Type 'c', 'p', 'u' → only /cpu matches → Enter
    result = _run([ord("c"), ord("p"), ord("u"), ord("\r")])
    assert result == "/cpu"
