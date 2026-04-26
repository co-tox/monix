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
    ("/cpu",     "CPU 사용률 + Load average"),
    ("/memory",  "메모리 사용량 상세"),
    ("/disk",    "디스크 사용량"),
    ("/swap",    "스왑 사용량"),
    ("/net",     "네트워크 I/O  인터페이스별 bps"),
    ("/io",      "디스크 I/O  읽기/쓰기 속도"),
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

NO_ARG_COMMANDS = {"/status", "/cpu", "/memory", "/disk", "/swap", "/net", "/io", "/clear", "/help", "/exit"}

# Fixed height: filter line + blank separator + one slot per command.
# Pre-allocating this many lines prevents terminal scroll during redraws.
_PICKER_BLOCK = 2 + len(COMMANDS)


def pick_with_filter() -> str | None:
    """라이브 필터 피커 — 고정 높이 블록을 미리 확보해 in-place 업데이트."""
    if not _HAS_TTY or not sys.stdout.isatty():
        return None

    N = len(COMMANDS)
    BLOCK = _PICKER_BLOCK  # filter(1) + blank(1) + items(N)

    query = ""
    idx = 0
    initialized = False

    def _items() -> list[tuple[str, str]]:
        if not query:
            return list(COMMANDS)
        prefix = ("/" + query).lower()
        return [(cmd, desc) for cmd, desc in COMMANDS if cmd.lower().startswith(prefix)]

    def _label() -> str:
        if query:
            return f"\033[36m/\033[1m{query}\033[0m"
        return "\033[36m/\033[0m"

    def _draw() -> None:
        nonlocal initialized
        items = _items()
        buf = []

        if not initialized:
            # Reserve BLOCK lines below the current prompt line P so that
            # subsequent redraws never trigger terminal scrolling.
            # "\r\n" × BLOCK lands cursor at col 0 of line P+BLOCK.
            buf.append("\r\n" * BLOCK)
            # Step back BLOCK-1 lines → P+1 (first line of the picker block).
            buf.append(f"\033[{BLOCK - 1}A\r")
            initialized = True
        else:
            # After the previous _draw(), cursor is at end of the last item
            # on line P+BLOCK. Go up BLOCK-1 to return to P+1.
            buf.append(f"\033[{BLOCK - 1}A\r")

        # P+1: filter bar
        buf.append(f"\r\033[K{_label()}\n")
        # P+2: blank separator
        buf.append(f"\r\033[K\n")
        # P+3 … P+N+2: always N fixed slots (blank-pad when filtered)
        for i in range(N):
            if not items:
                line = (
                    f"\r\033[K  \033[2m(일치하는 명령어 없음)\033[0m"
                    if i == 0 else "\r\033[K"
                )
            elif i < len(items):
                cmd, desc = items[i]
                if i == idx:
                    line = f"\r\033[K  \033[36m❯ {cmd:<12}\033[0m  \033[2m{desc}\033[0m"
                else:
                    line = f"\r\033[K    {cmd:<12}  \033[2m{desc}\033[0m"
            else:
                line = "\r\033[K"

            # No trailing \n on the last item — keeps cursor on P+BLOCK, not P+BLOCK+1
            buf.append(line + ("\n" if i < N - 1 else ""))

        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def _clear() -> None:
        """드롭다운을 지우고 커서를 프롬프트 줄(P) col 0 으로 복원."""
        buf = []
        # From P+BLOCK, go up to P+1 (filter line)
        buf.append(f"\033[{BLOCK - 1}A\r")
        # Erase lines P+1 … P+BLOCK-1 (each \n advances one line)
        for _ in range(BLOCK - 1):
            buf.append("\r\033[K\n")
        # Erase P+BLOCK without advancing (no \n)
        buf.append("\r\033[K")
        # Return to prompt line P
        buf.append(f"\033[{BLOCK}A\r")
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)
        _draw()

        while True:
            b = sys.stdin.buffer.read(1)

            if b == b"\x1b":
                b2 = sys.stdin.buffer.read(1)
                if b2 == b"[":
                    b3 = sys.stdin.buffer.read(1)
                    items = _items()
                    n = max(len(items), 1)
                    if b3 == b"A":
                        idx = (idx - 1) % n
                    elif b3 == b"B":
                        idx = (idx + 1) % n
                else:
                    _clear()
                    return None
            elif b in (b"\r", b"\n"):
                items = _items()
                selected = items[idx][0] if items else None
                _clear()
                return selected
            elif b in (b"\x03", b"\x04"):
                _clear()
                return None
            elif b == b"\x7f":
                if query:
                    query = query[:-1]
                    idx = 0
                else:
                    _clear()
                    return None
            else:
                try:
                    char = b.decode("utf-8")
                except UnicodeDecodeError:
                    char = ""
                if char.isprintable() and char != "/":
                    query += char
                    idx = 0
            _draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


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
