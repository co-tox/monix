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

NO_ARG_COMMANDS = {"/status", "/stat", "/cpu", "/memory", "/disk", "/swap", "/net", "/io", "/clear", "/help", "/exit"}

# Fixed height: filter line + blank separator + one slot per command.
_PICKER_BLOCK = 2 + len(COMMANDS)


def pick_with_filter() -> str | None:
    """라이브 필터 피커.

    - 고정 높이 블록 선점으로 in-place 업데이트 (스크롤 없음)
    - 한글 포함 멀티바이트 UTF-8 입력 지원
    - 좌/우 방향키로 필터 줄 안에서 커서 이동
    - 매 _draw() 완료 후 커서는 필터 줄(P+1) 안에 위치
    """
    if not _HAS_TTY or not sys.stdout.isatty():
        return None

    N = len(COMMANDS)
    BLOCK = _PICKER_BLOCK  # filter(1) + blank(1) + items(N)

    query_buf: list[str] = []   # 필터 문자 목록
    q_cursor = 0                # 필터 줄 커서 위치 (문자 단위)
    idx = 0                     # 선택된 항목 인덱스
    initialized = False
    pending = bytearray()       # 멀티바이트 누적 버퍼

    # ── 공통 유틸 ────────────────────────────────────────────────────
    def _cw(c: str) -> int:
        return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1

    def _q_width(chars) -> int:
        return sum(_cw(c) for c in chars)

    def _items() -> list[tuple[str, str]]:
        query = "".join(query_buf)
        if not query:
            return list(COMMANDS)
        prefix = ("/" + query).lower()
        return [(cmd, desc) for cmd, desc in COMMANDS if cmd.lower().startswith(prefix)]

    def _label() -> str:
        query = "".join(query_buf)
        if query:
            return f"\033[36m/\033[1m{query}\033[0m"
        return "\033[36m/\033[0m"

    # ── 렌더링 ───────────────────────────────────────────────────────
    def _draw() -> None:
        """고정 블록을 in-place 갱신하고 커서를 필터 줄(P+1) q_cursor 위치에 둔다."""
        nonlocal initialized
        items = _items()
        out = []

        if not initialized:
            # P+1 ~ P+BLOCK 라인을 미리 확보한다.
            # "\r\n" × BLOCK → 커서 P+BLOCK col 0
            out.append("\r\n" * BLOCK)
            # BLOCK-1 줄 위로 → P+1 col 0
            out.append(f"\033[{BLOCK - 1}A\r")
            initialized = True
        else:
            # 이전 _draw() 후 커서는 P+1(필터 줄) q_cursor 위치.
            # \r 로 col 0 으로 이동.
            out.append("\r")

        # P+1: 필터 줄
        out.append(f"\033[K{_label()}")

        # P+2: 빈 구분선  (\033[1B\r = 스크롤 없이 한 줄 아래 col 0)
        out.append("\033[1B\r\033[K")

        # P+3 ~ P+BLOCK: 항목 (항상 N 슬롯 — 필터링 결과 개수 무관)
        for i in range(N):
            out.append("\033[1B\r")
            if not items:
                content = "\033[2m(일치하는 명령어 없음)\033[0m" if i == 0 else ""
            elif i < len(items):
                cmd, desc = items[i]
                if i == idx:
                    content = f"\033[36m❯ {cmd:<12}\033[0m  \033[2m{desc}\033[0m"
                else:
                    content = f"  {cmd:<12}  \033[2m{desc}\033[0m"
            else:
                content = ""
            out.append(f"\033[K  {content}" if content else "\033[K")

        # 커서를 P+1(필터 줄) q_cursor 열로 복원
        # 현재 커서: P+BLOCK  →  BLOCK-1 줄 위로 이동 → P+1 col 0
        out.append(f"\033[{BLOCK - 1}A\r")
        # '/' 1열 + query_buf[:q_cursor] 의 표시 너비
        q_col = 1 + _q_width(query_buf[:q_cursor])
        out.append(f"\033[{q_col}C")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def _clear() -> None:
        """드롭다운을 지우고 커서를 프롬프트 줄(P) col 0 으로 복원.

        _draw() 후 커서는 P+1(필터 줄)에 있으므로 여기서 출발한다.
        """
        out = []
        out.append("\r")                        # P+1 col 0
        for _ in range(BLOCK - 1):
            out.append("\033[K\033[1B\r")       # 지우고 한 줄 아래 col 0
        out.append("\033[K")                    # P+BLOCK 지우기 (줄 이동 없음)
        out.append(f"\033[{BLOCK}A\r")          # P col 0 으로 복귀
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
                    elif b3 == b"H":  # Home
                        q_cursor = 0
                    elif b3 == b"F":  # End
                        q_cursor = len(query_buf)
                    elif b3.isdigit():
                        # \x1b[{숫자}~ 또는 \x1b[{숫자};…{letter} 전체 소비
                        seq = b3
                        while not (seq[-1:].isalpha() or seq.endswith(b"~")):
                            seq += sys.stdin.buffer.read(1)
                        if seq == b"3~" and q_cursor < len(query_buf):  # Delete
                            query_buf.pop(q_cursor)
                            idx = 0
                        elif seq in (b"1~", b"7~"):   # Home 변형
                            q_cursor = 0
                        elif seq in (b"4~", b"8~"):   # End 변형
                            q_cursor = len(query_buf)
                else:
                    _clear()
                    return None

            # ── Enter → 선택 ─────────────────────────────────────────
            elif b in (b"\r", b"\n"):
                items = _items()
                selected = items[idx][0] if items else None
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
