from __future__ import annotations

import sys

try:
    import termios
    import tty
    _HAS_TTY = True
except ImportError:
    _HAS_TTY = False


COMMANDS: list[tuple[str, str]] = [
    ("/status",  "서버 상태  CPU · 메모리 · 디스크"),
    ("/watch",   "실시간 모니터링  [초]"),
    ("/top",     "프로세스 TOP  [개수]"),
    ("/log",     "로그 관리  add·list·@alias·--live"),
    ("/logs",    "로그 보기 (기존)  [경로] [줄수]"),
    ("/service", "서비스 상태  <이름>"),
    ("/ask",     "Gemini 질문  <내용>"),
    ("/clear",   "대화 초기화"),
    ("/help",    "도움말"),
    ("/exit",    "종료"),
]

NO_ARG_COMMANDS = {"/status", "/clear", "/help", "/exit"}


def pick() -> str | None:
    """방향키로 명령어를 선택한다. 선택된 명령어 문자열을 반환하거나 취소 시 None."""
    if not _HAS_TTY or not sys.stdout.isatty():
        return None

    cmds = COMMANDS
    n = len(cmds)
    idx = 0
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    def _draw(first: bool = False) -> None:
        buf = []
        if not first:
            buf.append(f"\033[{n}A\r")
        for i, (cmd, desc) in enumerate(cmds):
            if i == idx:
                buf.append(f"  \033[36m❯ {cmd:<12}\033[0m  \033[2m{desc}\033[0m\033[K\n")
            else:
                buf.append(f"    {cmd:<12}  \033[2m{desc}\033[0m\033[K\n")
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def _clear() -> None:
        sys.stdout.write(f"\033[{n}A\r\033[J")
        sys.stdout.flush()

    try:
        tty.setraw(fd)
        sys.stdout.write("\n")
        _draw(first=True)
        while True:
            b = sys.stdin.buffer.read(1)
            if b == b"\x1b":
                b2 = sys.stdin.buffer.read(1)
                if b2 == b"[":
                    b3 = sys.stdin.buffer.read(1)
                    if b3 == b"A":
                        idx = (idx - 1) % n
                    elif b3 == b"B":
                        idx = (idx + 1) % n
                else:
                    _clear()
                    return None
            elif b in (b"\r", b"\n"):
                _clear()
                return cmds[idx][0]
            elif b in (b"\x03", b"\x04"):
                _clear()
                return None
            _draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
