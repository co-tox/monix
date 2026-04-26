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

NO_ARG_COMMANDS = {"/status", "/cpu", "/memory", "/disk", "/clear", "/help", "/exit"}


def pick_with_filter() -> str | None:
    """프롬프트 아래에 드롭다운으로 펼쳐지는 라이브 필터 피커.
    커서는 프롬프트 줄에 고정, 목록은 아래에 표시됨 (Codex 스타일)."""
    if not _HAS_TTY or not sys.stdout.isatty():
        return None

    query = ""
    idx = 0

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
        """프롬프트 줄에 /query 표시, 아래에 목록 렌더링 후 커서를 /query 끝으로 복원."""
        items = _items()
        buf = []
        # 저장된 위치(> 이후)로 복원 → /query 재작성 → 줄 끝 지우기
        buf.append(f"\033[u\033[K{_label()}")
        # 한 줄 아래로 이동 후 스크린 하단 전체 지우기
        buf.append("\033[1B\r\033[J")
        # 빈 줄(구분선) + 목록 항목
        buf.append("\n")
        if not items:
            buf.append("\r  \033[2m(일치하는 명령어 없음)\033[0m\033[K\n")
        else:
            for i, (cmd, desc) in enumerate(items):
                if i == idx:
                    buf.append(f"\r  \033[36m❯ {cmd:<12}\033[0m  \033[2m{desc}\033[0m\033[K\n")
                else:
                    buf.append(f"\r    {cmd:<12}  \033[2m{desc}\033[0m\033[K\n")
        # 저장 위치로 돌아와 /query 다시 써서 커서를 query 끝에 놓기
        buf.append(f"\033[u{_label()}")
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def _clear() -> None:
        """드롭다운 지우고 커서를 프롬프트 줄 맨 앞으로."""
        buf = []
        buf.append("\033[u\033[K")       # 저장 위치 복원 → / 포함 줄 끝까지 지우기
        buf.append("\033[1B\r\033[J")    # 한 줄 아래, 스크린 하단 전체 지우기
        buf.append("\033[1A\r")          # 프롬프트 줄 맨 앞으로 복귀
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)
        sys.stdout.write("\033[s")  # 현재 커서 위치 저장 (프롬프트 > 이후)
        sys.stdout.flush()
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
                _clear()
                return items[idx][0] if items else None
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
