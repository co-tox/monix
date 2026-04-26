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
    ("/stat",           "Snapshot / history  [all|cpu|memory|…] [period]"),
    ("/watch",          "Real-time watch  [all|cpu|memory|…] [sec]"),
    ("/collect",        "Collector  list·set·remove"),
    ("/top",            "Process TOP  [count]"),
    ("/service",        "Service status  <name>"),
    ("/docker",         "Docker  ps·stats·top·inspect·logs"),
    ("/log",            "Log management  add·list·@alias·--live"),
    ("/clear",          "Clear history"),
    ("/help",           "Help"),
    ("/exit",           "Exit"),
]

# Subcommand options revealed when the user types "<command> " (trailing space)
# in the picker — e.g. "log " expands to /log add, /log list, /log remove, ...
SUBCOMMANDS: dict[str, list[tuple[str, str]]] = {
    "/service": [
        ("list",   "List all services"),
    ],
    "/collect": [
        ("list",    "Show current configuration"),
        ("set",     "<interval> <retention> <folder>  Configure collector"),
        ("remove",  "Disable and remove collector"),
    ],
    "/log": [
        ("add",          "@alias -app|-nginx|-docker <path>  Register log"),
        ("list",         "List registered logs"),
        ("remove",       "@alias  Unregister log"),
        ("help",         "Show /log usage details"),
    ],
    "/docker": [
        ("ps",       "List running containers"),
        ("stats",    "[container]  CPU/mem/net/io usage"),
        ("top",      "<container|@alias>  Processes inside container"),
        ("inspect",  "<container|@alias>  Ports, mounts, env, health"),
        ("add",      "@alias <container>  Register alias"),
        ("list",     "List registered aliases"),
        ("logs",     "<container|@alias> [-n lines]  View logs"),
        ("search",   "<container|@alias> [pattern]  Search patterns"),
        ("live",     "<container|@alias> [-n lines]  Real-time stream"),
        ("remove",   "@alias  Unregister alias"),
        ("help",     "Show /docker usage details"),
    ],
    "/top": [
        ("cpu",     "[N]  Top N by CPU usage"),
        ("memory",  "[N]  Top N by memory usage"),
        ("disk",    "[N]  Disk partitions by usage"),
        ("all",     "[N]  All of the above  (default: 5)"),
        ("help",    "Show /top usage details"),
    ],
    "/watch": [
        ("all",     "[sec]  Watch all metrics  (default)"),
        ("cpu",     "Watch CPU usage  [sec]"),
        ("memory",  "Watch memory  [sec]"),
        ("disk",    "Watch disk  [sec]"),
        ("swap",    "Watch swap  [sec]"),
        ("net",     "Watch network  [sec]"),
        ("io",      "Watch disk I/O  [sec]"),
        ("help",    "Show /watch usage details"),
    ],
    "/stat": [
        ("all",     "[N]  All metrics snapshot  (default)"),
        ("cpu",     "CPU snapshot"),
        ("memory",  "Memory snapshot"),
        ("disk",    "Disk snapshot"),
        ("swap",    "Swap snapshot"),
        ("net",     "Network snapshot"),
        ("io",      "Disk I/O snapshot"),
        ("help",    "Show /stat usage details"),
    ],
}

NO_ARG_COMMANDS = {
    "/stat", "/watch", "/collect", "/service", "/top",
    "/clear", "/help", "/exit",
    # subcommands that take no further args — Enter immediately submits.
    "/log list", "/log help",
    "/stat help", "/watch help",
    "/top help", "/collect list", "/collect help",
    "/docker ps", "/docker list", "/docker stats", "/docker help",
}

# Fixed height = max(top-level, longest subcommand list) so subcommand views
# never overflow the reserved drop-down rows.
_PICKER_BLOCK = max(len(COMMANDS), *(len(v) for v in SUBCOMMANDS.values()))


def pick_with_filter(prompt_prefix: str = "") -> str | None:
    """Claude Code / Codex style live filter picker.

    Filter input is shown inline on prompt line (P),
    and the list items are rendered in-place at P+1 ~ P+N.

    Layout:
        P       monix > /stat              ← Prompt + Filter (inline)
        P+1     ❯ /status   Server Status   ← Selected (cyan + bold)
        P+2       /cpu      CPU Usage       ← Other items (dim)
        ...
    """
    if not _HAS_TTY or not sys.stdout.isatty():
        return None

    N = len(COMMANDS)
    BLOCK = _PICKER_BLOCK

    query_buf: list[str] = []
    q_cursor = 0
    idx = 0
    initialized = False
    pending = bytearray()

    # ── Utils ────────────────────────────────────────────────────────
    def _cw(c: str) -> int:
        return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1

    def _q_width(chars) -> int:
        return sum(_cw(c) for c in chars)

    def _vis_width(s: str) -> int:
        """Visual width of string excluding ANSI escape sequences."""
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
        query = "".join(query_buf).lstrip("/")
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
        """The /query string shown after prompt (with ANSI)."""
        query = "".join(query_buf).lstrip("/")
        if query:
            return f"\033[36m/\033[1m{query}\033[0m"
        return "\033[36m/\033[0m"

    # ── Rendering ────────────────────────────────────────────────────
    def _draw() -> None:
        nonlocal initialized
        items = _items()
        out = []

        if not initialized:
            # Pre-allocate P+1 ~ P+N lines. Cursor → P+N col 0
            out.append("\r\n" * BLOCK)
            # Move back up to P col 0
            out.append(f"\033[{BLOCK}A\r")
            initialized = True
        else:
            # After _draw(), cursor is at P q_cursor -> back to col 0
            out.append("\r")

        # P: Prompt + inline filter
        out.append(f"\033[K{prompt_prefix}{_filter_inline()}")

        # P+1 ~ P+BLOCK: Item slots (BLOCK rows reserved; empties at bottom if fewer items)
        for i in range(BLOCK):
            out.append("\033[1B\r")
            if not items:
                content = "\033[2m  (No matching commands)\033[0m" if i == 0 else ""
            elif i < len(items):
                cmd, desc = items[i]
                if i == idx:
                    # Selected: ❯ + cyan bold command + dim desc
                    content = (
                        f"\033[36m❯ \033[1m{cmd:<12}\033[0m"
                        f"  \033[2m{desc}\033[0m"
                    )
                else:
                    # Non-selected: all dim
                    content = f"\033[2m  {cmd:<12}  {desc}\033[0m"
            else:
                content = ""
            out.append(f"\033[K  {content}" if content else "\033[K")

        # Restore cursor to P q_cursor col
        # Currently at P+BLOCK -> move back up to P col 0
        out.append(f"\033[{BLOCK}A\r")
        # Prompt width + '/' char (1) + query prefix width
        q_col = _vis_width(prompt_prefix) + 1 + _q_width(query_buf[:q_cursor])
        out.append(f"\033[{q_col}C")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def _clear() -> None:
        """Clear dropdown and restore cursor to P col 0.

        Cursor is at P q_cursor col after _draw().
        """
        out = []
        out.append("\r\033[K")              # Clear P (cursor at P col 0)
        for _ in range(BLOCK):
            out.append("\033[1B\r\033[K")   # Clear P+1 ~ P+N
        out.append(f"\033[{BLOCK}A\r")      # Back to P col 0
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    # ── Event Loop ───────────────────────────────────────────────────
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)
        _draw()

        while True:
            b = sys.stdin.buffer.read(1)
            if not b:   # 실제 EOF
                _clear()
                return None

            # ── Escape Sequences ──────────────────────────────────────
            if b == b"\x1b":
                b2 = sys.stdin.buffer.read(1)
                if not b2:
                    _clear()
                    return None
                if b2 == b"[":
                    b3 = sys.stdin.buffer.read(1)
                    if not b3:
                        _clear()
                        return None
                    if b3 == b"A":    # 위 → 목록 위로
                        n = max(len(_items()), 1)
                        idx = (idx - 1) % n
                    elif b3 == b"B":  # Down -> Next item
                        n = max(len(_items()), 1)
                        idx = (idx + 1) % n
                    elif b3 == b"C":  # Right -> Move cursor
                        if q_cursor < len(query_buf):
                            q_cursor += 1
                    elif b3 == b"D":  # Left -> Move cursor
                        if q_cursor > 0:
                            q_cursor -= 1
                    elif b3 == b"H":  # Home
                        q_cursor = 0
                    elif b3 == b"F":  # End
                        q_cursor = len(query_buf)
                    elif b3.isdigit():
                        seq = b3
                        while not (seq[-1:].isalpha() or seq.endswith(b"~")):
                            chunk = sys.stdin.buffer.read(1)
                            if not chunk:
                                _clear()
                                return None
                            seq += chunk
                        if seq == b"3~" and q_cursor < len(query_buf):
                            query_buf.pop(q_cursor)
                            idx = 0
                        elif seq in (b"1~", b"7~"):  # Home
                            q_cursor = 0
                        elif seq in (b"4~", b"8~"):  # End
                            q_cursor = len(query_buf)
                else:
                    _clear()
                    return None

            # ── Enter → Select ───────────────────────────────────────
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

            # ── Ctrl-C / Ctrl-D → Cancel ─────────────────────────────
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

            # ── Normal Characters (UTF-8) ────────────────────────────
            else:
                pending.extend(b)
                while pending:
                    try:
                        char = pending.decode("utf-8")
                        pending.clear()
                        if char.isprintable():
                            query_buf.insert(q_cursor, char)
                            q_cursor += 1
                            idx = 0
                        break
                    except UnicodeDecodeError as exc:
                        if exc.reason == "unexpected end of data" and len(pending) < 4:
                            chunk = sys.stdin.buffer.read(1)
                            if not chunk:
                                pending.clear()
                                _clear()
                                return None
                            pending.extend(chunk)
                        else:
                            pending.clear()
                            break

            _draw()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def pick() -> str | None:
    """Select command using arrow keys. Return None if cancelled."""
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
