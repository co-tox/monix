from __future__ import annotations

import sys
import unicodedata

try:
    import termios
    import tty
    _HAS_TTY = True
except ImportError:
    _HAS_TTY = False


COMMANDS: list[tuple[str, str]] = [
    ("/exit",           "종료"),
    ("/help",           "도움말"),
    ("/clear",          "대화 초기화"),
    ("/ask",            "Gemini 질문  <내용>"),
    ("/service",        "서비스 상태  <이름>"),
    ("/docker",         "Docker  ps·logs·search·live"),
    ("/logs",           "로그 보기 (기존)  [경로] [줄수]"),
    ("/log",            "로그 관리  add·list·@alias·--live"),
    ("/top",            "프로세스 TOP  [개수]"),
    ("/watch",          "실시간 모니터링  [초]"),
    ("/io",             "디스크 I/O  읽기/쓰기 속도"),
    ("/net",            "네트워크 I/O  인터페이스별 bps"),
    ("/swap",           "스왑 사용량"),
    ("/disk",           "디스크 사용량"),
    ("/memory",         "메모리 사용량 상세"),
    ("/cpu",            "CPU 사용률 + Load average"),
    ("/stat",    "종합 단발 스냅샷  swap · net · io 포함"),
]

# Subcommand options revealed when the user types "<command> " (trailing space)
# in the picker — e.g. "log " expands to /log add, /log list, /log remove, ...
SUBCOMMANDS: dict[str, list[tuple[str, str]]] = {
    "/log": [
        ("add",          "@alias -app|-nginx|-docker <path>  로그 등록"),
        ("list",         "등록된 로그 목록"),
        ("remove",       "@alias  등록 해제"),
        ("docker-list",  "실행 중인 Docker 컨테이너 목록"),
    ],
    "/docker": [
        ("ps",      "실행 중인 컨테이너 목록"),
        ("add",     "@alias <container>  컨테이너 등록"),
        ("list",    "등록된 alias 목록"),
        ("logs",    "<container|@alias> [-n lines]  로그 보기"),
        ("search",  "<container|@alias> [pattern]  에러/패턴 검색"),
        ("live",    "<container|@alias> [-n lines]  실시간 스트리밍"),
        ("remove",  "@alias  등록 해제"),
    ],
    "/watch": [
        ("cpu",     "CPU 사용률 모니터링  [초]"),
        ("memory",  "메모리 모니터링  [초]"),
        ("disk",    "디스크 모니터링  [초]"),
        ("swap",    "스왑 모니터링  [초]"),
        ("net",     "네트워크 모니터링  [초]"),
        ("io",      "디스크 I/O 모니터링  [초]"),
    ],
    "/stat": [
        ("cpu",     "CPU 단발 스냅샷"),
        ("memory",  "메모리 단발 스냅샷"),
        ("disk",    "디스크 단발 스냅샷"),
        ("swap",    "스왑 단발 스냅샷"),
        ("net",     "네트워크 단발 스냅샷"),
        ("io",      "디스크 I/O 단발 스냅샷"),
    ],
}

NO_ARG_COMMANDS = {
    "/status", "/stat", "/cpu", "/memory", "/disk", "/swap", "/net", "/io",
    "/clear", "/help", "/exit",
    # subcommands that take no further args — Enter immediately submits.
    "/log list", "/log docker-list",
    "/docker ps", "/docker list",
}

# Fixed height = max(top-level, longest subcommand list) so subcommand views
# never overflow the reserved drop-down rows.
_PICKER_BLOCK = max(len(COMMANDS), *(len(v) for v in SUBCOMMANDS.values()))


def pick_with_filter(prompt_prefix: str = "") -> str | None:
    """Claude Code / Codex 스타일 라이브 필터 피커.

    필터 입력은 프롬프트 줄(P) 위에 인라인으로 표시되고,
    항목 목록은 P+1 ~ P+N 에 in-place 렌더링된다.

    레이아웃:
        P       monix > /stat              ← 프롬프트 + 필터 (인라인)
        P+1     ❯ /status   서버 상태       ← 선택된 항목 (cyan + bold)
        P+2       /cpu      CPU 사용률      ← 나머지 항목 (dim)
        ...
    """
    if not _HAS_TTY or not sys.stdout.isatty():
        return None

    N = len(COMMANDS)
    BLOCK = _PICKER_BLOCK  # = N  (items only; filter is on P)

    query_buf: list[str] = []
    q_cursor = 0
    idx = 0
    initialized = False
    pending = bytearray()

    # ── 유틸 ─────────────────────────────────────────────────────────
    def _cw(c: str) -> int:
        return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1

    def _q_width(chars) -> int:
        return sum(_cw(c) for c in chars)

    def _vis_width(s: str) -> int:
        """ANSI 시퀀스를 제거한 터미널 표시 너비."""
        w = 0
        in_esc = False
        for c in s:
            if c == "\033":
                in_esc = True
                continue
            if in_esc:
                if c == "m":
                    in_esc = False
                continue
            w += _cw(c)
        return w

    def _items() -> list[tuple[str, str]]:
        query = "".join(query_buf)
        if not query:
            return list(COMMANDS)

        # Subcommand mode: "log " / "log a" / "docker ps" → expand SUBCOMMANDS
        if " " in query:
            head, _, sub_query = query.partition(" ")
            head_cmd = "/" + head.lower()
            if head_cmd in SUBCOMMANDS:
                sub_prefix = sub_query.lower()
                return [
                    (f"{head_cmd} {sub}", desc)
                    for sub, desc in SUBCOMMANDS[head_cmd]
                    if sub.lower().startswith(sub_prefix)
                ]
            # Unknown command before the space — fall back to filtering by the
            # head only so the user still sees something useful.
            prefix = head_cmd
        else:
            prefix = ("/" + query).lower()

        return [(cmd, desc) for cmd, desc in COMMANDS if cmd.lower().startswith(prefix)]

    def _filter_inline() -> str:
        """프롬프트 뒤에 붙는 /query 문자열 (ANSI 포함)."""
        query = "".join(query_buf)
        if query:
            return f"\033[36m/\033[1m{query}\033[0m"
        return "\033[36m/\033[0m"

    # ── 렌더링 ───────────────────────────────────────────────────────
    def _draw() -> None:
        nonlocal initialized
        items = _items()
        out = []

        if not initialized:
            # P+1 ~ P+N 라인 미리 확보. 커서 → P+N col 0
            out.append("\r\n" * BLOCK)
            # BLOCK 줄 위로 → P col 0
            out.append(f"\033[{BLOCK}A\r")
            initialized = True
        else:
            # _draw() 완료 후 커서는 P q_cursor 열 → \r 로 col 0
            out.append("\r")

        # P: 프롬프트 + 필터 인라인
        out.append(f"\033[K{prompt_prefix}{_filter_inline()}")

        # P+1 ~ P+N: 항목 슬롯 (항상 N 개, 내용 없으면 빈 줄)
        for i in range(N):
            out.append("\033[1B\r")
            if not items:
                content = "\033[2m  (일치하는 명령어 없음)\033[0m" if i == 0 else ""
            elif i < len(items):
                cmd, desc = items[i]
                if i == idx:
                    # 선택된 항목: ❯ + cyan bold 명령 + dim 설명
                    content = (
                        f"\033[36m❯ \033[1m{cmd:<12}\033[0m"
                        f"  \033[2m{desc}\033[0m"
                    )
                else:
                    # 비선택: 모두 dim
                    content = f"\033[2m  {cmd:<12}  {desc}\033[0m"
            else:
                content = ""
            out.append(f"\033[K  {content}" if content else "\033[K")

        # 커서를 P q_cursor 열로 복원
        # 현재 위치 P+N → BLOCK 줄 위로 → P col 0
        out.append(f"\033[{BLOCK}A\r")
        # 프롬프트 가시 너비 + '/' 1열 + query[:q_cursor] 너비
        q_col = _vis_width(prompt_prefix) + 1 + _q_width(query_buf[:q_cursor])
        out.append(f"\033[{q_col}C")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def _clear() -> None:
        """드롭다운 소거 후 커서를 P col 0 으로 복원.

        _draw() 완료 후 커서는 P q_cursor 열에 있다.
        """
        out = []
        out.append("\r\033[K")              # P 지우기 (커서 P col 0)
        for _ in range(BLOCK):
            out.append("\033[1B\r\033[K")   # P+1 ~ P+N 지우기
        out.append(f"\033[{BLOCK + 1}A\r")  # 다시 P col 0 으로
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    # ── 이벤트 루프 ──────────────────────────────────────────────────
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)
        _draw()

        while True:
            b = sys.stdin.buffer.read(1)

            # ── Escape 시퀀스 ────────────────────────────────────────
            if b == b"\x1b":
                b2 = sys.stdin.buffer.read(1)
                if b2 == b"[":
                    b3 = sys.stdin.buffer.read(1)
                    if b3 == b"A":    # 위 → 목록 위로
                        n = max(len(_items()), 1)
                        idx = (idx - 1) % n
                    elif b3 == b"B":  # 아래 → 목록 아래로
                        n = max(len(_items()), 1)
                        idx = (idx + 1) % n
                    elif b3 == b"C":  # 오른쪽 → 필터 커서 오른쪽
                        if q_cursor < len(query_buf):
                            q_cursor += 1
                    elif b3 == b"D":  # 왼쪽 → 필터 커서 왼쪽
                        if q_cursor > 0:
                            q_cursor -= 1
                    elif b3 == b"H":
                        q_cursor = 0
                    elif b3 == b"F":
                        q_cursor = len(query_buf)
                    elif b3.isdigit():
                        seq = b3
                        while not (seq[-1:].isalpha() or seq.endswith(b"~")):
                            seq += sys.stdin.buffer.read(1)
                        if seq == b"3~" and q_cursor < len(query_buf):
                            query_buf.pop(q_cursor)
                            idx = 0
                        elif seq in (b"1~", b"7~"):
                            q_cursor = 0
                        elif seq in (b"4~", b"8~"):
                            q_cursor = len(query_buf)
                else:
                    _clear()
                    return None

            # ── Enter → 선택 ─────────────────────────────────────────
            elif b in (b"\r", b"\n"):
                items = _items()
                if items:
                    selected = items[idx][0]
                elif query_buf:
                    selected = "/" + "".join(query_buf)
                else:
                    selected = None
                _clear()
                return selected

            # ── Ctrl-C / Ctrl-D → 취소 ───────────────────────────────
            elif b in (b"\x03", b"\x04"):
                _clear()
                return None

            # ── Ctrl-A / Ctrl-E ──────────────────────────────────────
            elif b == b"\x01":
                q_cursor = 0
            elif b == b"\x05":
                q_cursor = len(query_buf)

            # ── Backspace ────────────────────────────────────────────
            elif b == b"\x7f":
                if q_cursor > 0:
                    query_buf.pop(q_cursor - 1)
                    q_cursor -= 1
                    idx = 0
                elif not query_buf:
                    _clear()
                    return None

            # ── 일반 문자 (멀티바이트 UTF-8 포함) ───────────────────
            else:
                pending.extend(b)
                while pending:
                    try:
                        char = pending.decode("utf-8")
                        pending.clear()
                        if char.isprintable() and char != "/":
                            query_buf.insert(q_cursor, char)
                            q_cursor += 1
                            idx = 0
                        break
                    except UnicodeDecodeError as exc:
                        if exc.reason == "unexpected end of data" and len(pending) < 4:
                            pending.extend(sys.stdin.buffer.read(1))
                        else:
                            pending.clear()
                            break

            _draw()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def pick() -> str | None:
    """방향키로 명령어를 선택한다. 취소 시 None."""
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
                buf.append(f"  \033[36m❯ \033[1m{cmd:<12}\033[0m  \033[2m{desc}\033[0m\033[K\n")
            else:
                buf.append(f"  \033[2m  {cmd:<12}  {desc}\033[0m\033[K\n")
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
