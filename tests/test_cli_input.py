"""Tests for _read_line TTY input handling in cli.py."""
from unittest.mock import MagicMock, patch

import pytest

import monix.cli as _cli_module
from monix.cli import _read_line


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_buf(byte_seq):
    """Mock stdin.buffer that feeds bytes from *byte_seq* one at a time."""
    it = iter(byte_seq)

    def _read(n=1):  # noqa: ARG001
        try:
            return bytes([next(it)])
        except StopIteration:
            return b""

    mock = MagicMock(name="stdin.buffer")
    mock.read.side_effect = _read
    return mock


def _run(byte_seq, prompt_str="\nmonix > "):
    """Run _read_line against a simulated byte sequence; return the result string."""
    mock_termios = MagicMock(name="termios")
    mock_termios.tcgetattr.return_value = []
    mock_termios.TCSADRAIN = 1
    mock_tty = MagicMock(name="tty")

    with (
        patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
        patch("os.isatty", return_value=True),
        patch("sys.stdout.write"),
        patch("sys.stdout.flush"),
        patch("sys.stdin") as mock_stdin,
    ):
        mock_stdin.fileno.return_value = 0
        mock_stdin.buffer = _make_buf(byte_seq)
        return _read_line(prompt_str)


# ── Backspace ─────────────────────────────────────────────────────────────────


def test_backspace_del_x7f_removes_last_char():
    assert _run([ord("a"), ord("b"), 0x7F, ord("\r")]) == "a"


def test_backspace_bs_x08_removes_last_char():
    """MobaXterm and some SSH clients send \\x08 (BS) instead of \\x7F for Backspace."""
    assert _run([ord("a"), ord("b"), 0x08, ord("\r")]) == "a"


def test_backspace_del_at_start_is_ignored():
    assert _run([0x7F, ord("a"), ord("\r")]) == "a"


def test_backspace_bs_at_start_is_ignored():
    assert _run([0x08, ord("a"), ord("\r")]) == "a"


def test_backspace_del_removes_correct_char_mid_line():
    # "abc" → Left → Backspace → enter ⟹ "ac"
    seq = (
        [ord("a"), ord("b"), ord("c")]
        + [0x1B, ord("["), ord("D")]  # Left
        + [0x7F, ord("\r")]
    )
    assert _run(seq) == "ac"


def test_backspace_bs_removes_correct_char_mid_line():
    seq = (
        [ord("a"), ord("b"), ord("c")]
        + [0x1B, ord("["), ord("D")]  # Left
        + [0x08, ord("\r")]
    )
    assert _run(seq) == "ac"


# ── Ctrl shortcuts ────────────────────────────────────────────────────────────


def test_ctrl_u_clears_entire_line():
    assert _run([ord("a"), ord("b"), ord("c"), 0x15, ord("\r")]) == ""


def test_ctrl_k_kills_from_cursor_to_end():
    # "abc" → Left × 2 → Ctrl-K → Enter ⟹ "a"
    seq = (
        [ord("a"), ord("b"), ord("c")]
        + [0x1B, ord("["), ord("D")] * 2  # Left × 2
        + [0x0B, ord("\r")]
    )
    assert _run(seq) == "a"


def test_ctrl_w_deletes_previous_word():
    seq = [ord(c) for c in "hello world"] + [0x17, ord("\r")]
    assert _run(seq) == "hello "


def test_ctrl_a_moves_cursor_to_start():
    seq = [ord("a"), ord("b"), 0x01, ord("X"), ord("\r")]
    assert _run(seq) == "Xab"


def test_ctrl_e_moves_cursor_to_end():
    seq = [ord("a"), ord("b"), 0x01, 0x05, ord("X"), ord("\r")]
    assert _run(seq) == "abX"


# ── Arrow keys ────────────────────────────────────────────────────────────────


def test_left_right_arrows_allow_mid_insert():
    seq = (
        [ord("a"), ord("b")]
        + [0x1B, ord("["), ord("D")]  # Left
        + [ord("X"), ord("\r")]
    )
    assert _run(seq) == "aXb"


def test_left_at_start_does_not_move():
    seq = (
        [ord("a")]
        + [0x1B, ord("["), ord("D")] * 5  # Left × 5 (beyond start)
        + [ord("X"), ord("\r")]
    )
    assert _run(seq) == "Xa"


def test_right_at_end_does_not_move():
    seq = (
        [ord("a"), ord("b")]
        + [0x1B, ord("["), ord("C")] * 5  # Right × 5 (beyond end)
        + [ord("X"), ord("\r")]
    )
    assert _run(seq) == "abX"


# ── Delete key ────────────────────────────────────────────────────────────────


def test_delete_key_x1b_3_tilde():
    # "ab" → Left → Delete → Enter ⟹ "a"
    seq = (
        [ord("a"), ord("b")]
        + [0x1B, ord("["), ord("D")]
        + [0x1B, ord("["), ord("3"), ord("~")]
        + [ord("\r")]
    )
    assert _run(seq) == "a"


def test_delete_at_end_does_nothing():
    seq = (
        [ord("a"), ord("b")]
        + [0x1B, ord("["), ord("3"), ord("~")]  # Delete at end
        + [ord("\r")]
    )
    assert _run(seq) == "ab"


# ── Home / End ────────────────────────────────────────────────────────────────


def test_home_key_moves_to_start():
    seq = [ord("a"), ord("b"), 0x1B, ord("["), ord("H"), ord("X"), ord("\r")]
    assert _run(seq) == "Xab"


def test_end_key_moves_to_end():
    seq = (
        [ord("a"), ord("b")]
        + [0x1B, ord("["), ord("H")]
        + [0x1B, ord("["), ord("F")]
        + [ord("X"), ord("\r")]
    )
    assert _run(seq) == "abX"


# ── Enter / EOF / Interrupt ───────────────────────────────────────────────────


def test_enter_cr_returns_buffer():
    assert _run([ord("h"), ord("i"), ord("\r")]) == "hi"


def test_enter_lf_returns_buffer():
    assert _run([ord("h"), ord("i"), ord("\n")]) == "hi"


def test_ctrl_c_raises_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        _run([ord("a"), 0x03])


def test_ctrl_d_on_empty_raises_eof():
    with pytest.raises(EOFError):
        _run([0x04])


def test_ctrl_d_with_content_does_not_raise():
    assert _run([ord("a"), 0x04, ord("\r")]) == "a"


# ── UTF-8 multi-byte characters ───────────────────────────────────────────────


def test_utf8_korean_character():
    seq = list("가".encode("utf-8")) + [ord("\r")]
    assert _run(seq) == "가"


def test_utf8_emoji():
    seq = list("😀".encode("utf-8")) + [ord("\r")]
    assert _run(seq) == "😀"


def test_backspace_del_after_multibyte_removes_whole_char():
    seq = list("가".encode("utf-8")) + [0x7F, ord("\r")]
    assert _run(seq) == ""


def test_backspace_bs_after_multibyte_removes_whole_char():
    seq = list("가".encode("utf-8")) + [0x08, ord("\r")]
    assert _run(seq) == ""


# ── History navigation ────────────────────────────────────────────────────────


def test_history_up_recalls_previous_entry(monkeypatch):
    monkeypatch.setattr(_cli_module, "_HISTORY", ["prev_cmd"])
    seq = [0x1B, ord("["), ord("A"), ord("\r")]  # Up → Enter
    assert _run(seq) == "prev_cmd"


def test_history_down_clears_after_last(monkeypatch):
    monkeypatch.setattr(_cli_module, "_HISTORY", ["cmd1"])
    seq = (
        [0x1B, ord("["), ord("A")]  # Up → "cmd1"
        + [0x1B, ord("["), ord("B")]  # Down → clears
        + [ord("\r")]
    )
    assert _run(seq) == ""


def test_history_up_on_empty_history_does_nothing(monkeypatch):
    monkeypatch.setattr(_cli_module, "_HISTORY", [])
    seq = [0x1B, ord("["), ord("A"), ord("a"), ord("\r")]
    assert _run(seq) == "a"
