from __future__ import annotations

import argparse
import dataclasses
import itertools
import shutil
import shlex
import sys
import threading
import time
import unicodedata
import os
from pathlib import Path

from monix import __version__
from monix.config import Settings
from monix.config.settings import GEMINI_PROVIDER, OPENAI_CODEX_PROVIDER, default_model
from monix.core.assistant import answer, infer_service_name, local_answer
from monix.tools.collect import (
    CollectorConfig,
    collect_and_save,
    load_config as load_collector_config,
    load_history,
    metrics_path,
    prune_metrics_file,
    save_config as save_collector_config,
)
from monix.picker import NO_ARG_COMMANDS, pick, pick_with_filter
from monix.tools.logs import follow_log, registry, search_log, tail_log
from monix.tools.logs.docker import follow_container, list_containers, search_container, tail_container
from monix.tools.services import list_services, service_status
from monix.tools.logs.nginx import tail_nginx_access
from monix.render import (
    badge,
    clear_screen,
    colorize_log_line,
    prompt,
    render_docker_aliases,
    render_docker_containers,
    render_docker_inspect,
    render_docker_stats,
    render_docker_top,
    render_cpu,
    render_disk,
    render_disk_io,
    render_log_aliases,
    render_log_list,
    render_log_search,
    render_logs,
    render_nginx_summary,
    render_memory,
    render_network,
    render_reply,
    render_history,
    render_processes,
    render_top,
    render_service,
    render_service_list,
    render_snapshot,
    render_stat,
    render_swap,
    render_tool_done,
    render_tool_fail,
    render_tool_start,
    render_welcome,
    style,
)
from monix.tools.system import (
    collect_snapshot,
    container_inspect,
    container_processes,
    container_stats,
    cpu_core_usage_percents,
    cpu_usage_percent,
    disk_info,
    disk_io,
    load_average,
    memory_info,
    network_io,
    swap_info,
    all_processes,
    top_processes,
    uptime_seconds_value,
)

HELP = """Commands:
  /cpu                             CPU usage + load average + cores
  /memory                          Memory usage
  /disk                            Disk usage
  /swap                            Swap usage
  /net                             Network I/O
  /io                              Disk I/O
  /top [cpu|memory|disk|all] [N]   Top processes
  /top help                        Show /top usage details
  /service all                     List all running services
  /service <name>                  Check systemd service status

  /stat [all|cpu|mem|disk|swap|net|io]  Snapshot or history view
  /stat help                       Show /stat usage details
  /watch [all|cpu|mem|disk|swap|net|io] [sec]  Real-time monitoring
  /watch help                      Show /watch usage details
  /collect list                    Show collector configuration
  /collect set <interval> <retention> <folder>  Configure collector
  /collect remove                  Disable and remove collector
  /collect help                    Show /collect usage details
  /log add @alias -app <path>      Register app log
  /log add @alias -nginx <path>    Register Nginx log
  /log add @alias -docker <name>   Register Docker container log
  /log list                        List registered logs
  /log @                           Show registered aliases
  /log @alias [-n lines]           View registered log
  /log @alias --search [pattern]   Search error/warn (default: error filter)
  /log @alias --live [-n lines]    Real-time log streaming
  /log /path/to/file [-n lines]    Direct path view (no registration needed)
  /log /path/to/file --live        Direct path real-time streaming
  /log remove @alias               Unregister log
  /log help                        Show /log usage details

  /docker ps                       List running containers
  /docker stats [container]        Resource usage (CPU/mem/net/io)
  /docker top <container>          Processes inside a container
  /docker inspect <container>      Ports, mounts, env, health
  /docker add @alias <container>   Register container alias
  /docker list                     List registered Docker aliases
  /docker @alias [-n lines]        View registered container logs
  /docker @alias --search [pat]    Search error/pattern
  /docker @alias --live            Real-time streaming
  /docker remove @alias            Unregister alias
  /docker logs <container>         View container logs directly [-n lines]
  /docker search <container> [pattern] [-n lines]  Search error/pattern (direct)
  /docker live <container>         Real-time streaming (direct) [-n lines]
  /docker help                     Show /docker usage details

  /logs <path> [lines]             Direct log view
  /notify set log-errors on|off    Toggle log error webhook alerts
  /notify test [discord|slack]     Send test alert to webhook
  /notify status                   Show webhook configuration and last sent time
  /notify help                     Show /notify usage details
  /ask <question>                  Ask the configured LLM provider
  /clear                           Clear conversation history
  /help                            Show this help
  /exit                            Exit


You can also ask in natural language:
  "Why is the CPU so high?"  "Check nginx service"  "When will memory run out?"
  "Find errors in @api logs"  "Search for timeout in @nginx"\""""


_HISTORY: list[str] = []

_collector_stop: threading.Event = threading.Event()
_collector_thread: threading.Thread | None = None
_collector_last_error: str | None = None
_collector_last_saved: str | None = None


def _start_collector(cfg: CollectorConfig) -> None:
    global _collector_thread, _collector_stop, _collector_last_error, _collector_last_saved
    _collector_stop.set()
    _collector_stop = threading.Event()
    stop = _collector_stop

    interval_sec = cfg.interval_days * 86400

    def _run() -> None:
        global _collector_last_error, _collector_last_saved
        while True:
            try:
                path = collect_and_save(cfg.folder)
                if cfg.retention_days > 0:
                    prune_metrics_file(cfg.folder, cfg.retention_days)
                _collector_last_saved = path
                _collector_last_error = None
            except Exception as exc:
                _collector_last_error = str(exc) or type(exc).__name__
            if stop.wait(interval_sec):
                break

    _collector_thread = threading.Thread(target=_run, daemon=True, name="monix-collector")
    _collector_thread.start()


def _is_panel_output(text: str) -> bool:
    """Detect if the output is a box-drawing panel (skips render_reply)."""
    s = text.lstrip("\n")
    while s.startswith("\033["):
        end = s.find("m")
        if end == -1:
            break
        s = s[end + 1:]
    return s.startswith("┌")


def _read_line(prompt_str: str) -> str:
    """Read one line from raw TTY.

    Supports:
    - Multi-byte UTF-8
    - Left/Right arrow cursor movement, Delete key
    - Up/Down arrow history navigation
    - Ctrl-A/E/K/U/W readline shortcuts
    - '/' as first character triggers live picker
    """
    try:
        import termios as _T
        import tty as _tty
    except ImportError:
        # Fallback for systems without termios (e.g. basic Windows CMD)
        return input(prompt_str)

    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return input(prompt_str)

    # Emit the prompt's leading newlines (and the prompt itself) exactly once.
    sys.stdout.write(prompt_str)
    sys.stdout.flush()
    prompt_line = prompt_str.lstrip("\n")

    saved = _T.tcgetattr(fd)
    _tty.setraw(fd)
    buf: list[str] = []
    cursor_pos = 0
    hist_pos = len(_HISTORY)
    pending = bytearray()

    def _cw(c: str) -> int:
        """Terminal column width (2 for full-width, 1 otherwise)."""
        return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1

    def _width(chars) -> int:
        return sum(_cw(c) for c in chars)

    def _redraw() -> None:
        """Redraw the input line in place (no leading newline)."""
        sys.stdout.write("\r\x1b[K")
        sys.stdout.write(prompt_line + "".join(buf))
        w = _width(buf[cursor_pos:])
        if w > 0:
            sys.stdout.write(f"\x1b[{w}D")
        sys.stdout.flush()

    try:
        while True:
            b = sys.stdin.buffer.read(1)
            if not b:   # EOF
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise EOFError

            # ── Enter ────────────────────────────────────────────────
            if b in (b"\r", b"\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buf)

            # ── Ctrl-C ───────────────────────────────────────────────
            if b == b"\x03":
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise KeyboardInterrupt

            # ── Ctrl-D ───────────────────────────────────────────────
            if b == b"\x04":
                if not buf:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    raise EOFError
                continue

            # ── Backspace ────────────────────────────────────────────
            if b == b"\x7f":
                if cursor_pos > 0:
                    buf.pop(cursor_pos - 1)
                    cursor_pos -= 1
                    _redraw()
                continue

            # ── Readline shortcuts ───────────────────────────────────
            if b == b"\x01":   # Ctrl-A
                cursor_pos = 0
                _redraw()
                continue
            if b == b"\x05":   # Ctrl-E
                cursor_pos = len(buf)
                _redraw()
                continue
            if b == b"\x0b":   # Ctrl-K
                del buf[cursor_pos:]
                _redraw()
                continue
            if b == b"\x15":   # Ctrl-U
                buf.clear()
                cursor_pos = 0
                _redraw()
                continue
            if b == b"\x17":   # Ctrl-W
                while cursor_pos > 0 and buf[cursor_pos - 1] == " ":
                    buf.pop(cursor_pos - 1)
                    cursor_pos -= 1
                while cursor_pos > 0 and buf[cursor_pos - 1] != " ":
                    buf.pop(cursor_pos - 1)
                    cursor_pos -= 1
                _redraw()
                continue
            if b == b"\x0c":  # Ctrl-L
                sys.stdout.write(clear_screen())
                _redraw()
                continue

            # ── Escape sequences (arrows, home, end, delete) ──────────
            if b == b"\x1b":
                b2 = sys.stdin.buffer.read(1)
                if not b2:
                    raise EOFError
                if b2 == b"[":
                    b3 = sys.stdin.buffer.read(1)
                    if not b3:
                        raise EOFError
                    if b3 == b"A":    # Up — previous history
                        if _HISTORY:
                            hist_pos = max(0, hist_pos - 1)
                            buf[:] = list(_HISTORY[hist_pos])
                            cursor_pos = len(buf)
                            _redraw()
                    elif b3 == b"B":  # Down — next history
                        if hist_pos < len(_HISTORY) - 1:
                            hist_pos += 1
                            buf[:] = list(_HISTORY[hist_pos])
                            cursor_pos = len(buf)
                        else:
                            hist_pos = len(_HISTORY)
                            buf.clear()
                            cursor_pos = 0
                        _redraw()
                    elif b3 == b"C":  # Right
                        if cursor_pos < len(buf):
                            cursor_pos += 1
                            _redraw()
                    elif b3 == b"D":  # Left
                        if cursor_pos > 0:
                            cursor_pos -= 1
                            _redraw()
                    elif b3 == b"H":  # Home
                        cursor_pos = 0
                        _redraw()
                    elif b3 == b"F":  # End
                        cursor_pos = len(buf)
                        _redraw()
                    elif b3.isdigit():
                        # \x1b[{number}~ or \x1b[{number};…{letter}
                        seq = b3
                        while not (seq[-1:].isalpha() or seq.endswith(b"~")):
                            chunk = sys.stdin.buffer.read(1)
                            if not chunk:
                                raise EOFError
                            seq += chunk
                        if seq == b"3~" and cursor_pos < len(buf):   # Delete
                            buf.pop(cursor_pos)
                            _redraw()
                        elif seq in (b"1~", b"7~"):   # Home variants
                            cursor_pos = 0
                            _redraw()
                        elif seq in (b"4~", b"8~"):   # End variants
                            cursor_pos = len(buf)
                            _redraw()
                continue

            # ── Live Picker Trigger ──────────────────────────────────
            if b == b"/" and not buf:
                _T.tcsetattr(fd, _T.TCSADRAIN, saved)
                result = pick_with_filter(prompt_line)
                if result:
                    sys.stdout.write(f"\r\033[K{prompt_line}{result}\n")
                    sys.stdout.flush()
                    return result
                # Picker cancelled
                sys.stdout.write(f"\r\033[K{prompt_line}")
                sys.stdout.flush()
                _tty.setraw(fd)
                _redraw()
                continue

            # ── Normal characters (including Multi-byte UTF-8) ────────
            pending.extend(b)
            while pending:
                try:
                    char = pending.decode("utf-8")
                    pending.clear()
                    if char.isprintable():
                        buf.insert(cursor_pos, char)
                        cursor_pos += 1
                        _redraw()
                    break
                except UnicodeDecodeError as exc:
                    # Incomplete multi-byte sequence → read more bytes
                    if exc.reason == "unexpected end of data" and len(pending) < 4:
                        chunk = sys.stdin.buffer.read(1)
                        if not chunk:
                            pending.clear()
                            raise EOFError
                        pending.extend(chunk)
                    else:
                        pending.clear()
                        break

    finally:
        _T.tcsetattr(fd, _T.TCSADRAIN, saved)


class Spinner:
    def __init__(self, message: str = "Loading..."):
        self.message = message
        self.spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._spin)

    def _spin(self) -> None:
        while not self.stop_event.is_set():
            sys.stdout.write(f"\r  {style(next(self.spinner), 'cyan')}  {self.message}")
            sys.stdout.flush()
            time.sleep(0.1)
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()

    def __enter__(self):
        if sys.stdout.isatty():
            self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.thread.is_alive():
            self.stop_event.set()
            self.thread.join()


def _prompt_platform_setup(settings: Settings) -> Settings:
    from monix.config.keystore import save_platform
    from monix.picker import pick_option

    detected = settings.platform
    default_idx = 1 if detected == "mac" else 0
    options = [
        ("Linux", "Ubuntu, Debian, RHEL, …"),
        ("macOS", "Apple Silicon / Intel"),
    ]
    idx = pick_option(f"Select your platform  (auto-detected: {detected})", options, default=default_idx)
    if idx is None:
        return settings
    platform_val = "mac" if idx == 1 else "linux"
    save_platform(platform_val)
    print(f"\n  ✓ Platform set to '{platform_val}'.\n")
    return dataclasses.replace(settings, platform=platform_val)


def _prompt_llm_provider_setup(settings: Settings) -> Settings:
    from monix.picker import pick_option

    idx = pick_option(
        "Select LLM provider",
        [
            ("Gemini", "Gemini API key"),
            ("OpenAI Codex", "Codex CLI login from this user"),
        ],
    )
    if idx == 0:
        return _setup_gemini_provider(_with_llm_provider(settings, GEMINI_PROVIDER))
    if idx == 1:
        return _setup_codex_provider(_with_llm_provider(settings, OPENAI_CODEX_PROVIDER))
    return settings


def _setup_llm_provider(settings: Settings) -> Settings:
    if settings.llm_provider == GEMINI_PROVIDER:
        return _setup_gemini_provider(settings)
    if settings.llm_provider == OPENAI_CODEX_PROVIDER:
        return _setup_codex_provider(settings)
    return _prompt_llm_provider_setup(settings)


def _with_llm_provider(settings: Settings, provider: str) -> Settings:
    model = settings.model
    if settings.llm_provider is None and model == default_model(None):
        model = default_model(provider)
    return dataclasses.replace(settings, llm_provider=provider, model=model)


def _setup_gemini_provider(settings: Settings) -> Settings:
    from monix.config.keystore import save_llm_provider, save_model

    settings = _with_llm_provider(settings, GEMINI_PROVIDER)
    if not settings.gemini_api_key:
        settings = _prompt_api_key_setup(settings)
    if settings.gemini_api_key:
        save_llm_provider(GEMINI_PROVIDER)
        save_model(settings.model)
    return settings


def _setup_codex_provider(settings: Settings) -> Settings:
    from monix.config.keystore import save_llm_provider, save_model

    settings = _with_llm_provider(settings, OPENAI_CODEX_PROVIDER)
    if not shutil.which("codex"):
        print(
            "\n  Codex CLI is required for the OpenAI Codex provider.\n"
            "  Install Codex CLI in this environment, run: codex login\n"
            "  Then restart monix.\n"
        )
        return settings

    if not _codex_auth_is_present(_codex_auth_path()):
        print(
            "\n  OpenAI Codex auth was not found.\n\n"
            "  Run:\n"
            "    codex login\n\n"
            "  Then restart monix.\n"
        )
        return settings

    save_llm_provider(OPENAI_CODEX_PROVIDER)
    save_model(settings.model)
    print("\n  OpenAI Codex provider configured from current-user Codex CLI auth.\n")
    return settings


def _codex_auth_path() -> Path:
    return Path.home() / ".codex" / "auth.json"


def _codex_auth_is_present(path: Path) -> bool:
    from monix.llm.providers.codex import load_codex_auth

    return load_codex_auth(path) is not None


def _prompt_api_key_setup(settings: Settings) -> Settings:
    import getpass
    from monix.config.keystore import save_api_key
    from monix.llm.gemini import GeminiClient

    print("\n  Gemini API key is required to use monix.")
    print("  Get a free key at: https://aistudio.google.com/app/apikey")
    print("  Pasting is supported (input is hidden for security).\n")
    for attempt in range(3):
        try:
            key = getpass.getpass("  Gemini API Key: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except UnicodeDecodeError:
            print("\r  ✗ Input encoding error. Please paste the key again.          ")
            continue
        if not key:
            break
        print("  Validating key...", end="", flush=True)
        ok, err = GeminiClient.validate(key, settings.model)
        if ok:
            save_api_key(key)
            print("\r  ✓ API key saved.                       ")
            return dataclasses.replace(settings, gemini_api_key=key)
        else:
            remaining = 2 - attempt
            msg = f"\r  ✗ Invalid key. ({err})"
            if remaining > 0:
                msg += f" Try again. ({remaining} attempts left)"
            print(msg + "             ")
    print("\n  No API key set. Run monix again or set the GEMINI_API_KEY environment variable.\n")
    return settings


def repl(settings: Settings | None = None) -> int:
    settings = settings or Settings.from_env()
    if not settings.llm_provider:
        settings = _prompt_llm_provider_setup(settings)
        if not settings.llm_provider:
            return 1
    if settings.llm_provider == GEMINI_PROVIDER and not settings.gemini_api_key:
        settings = _setup_gemini_provider(settings)
        if not settings.gemini_api_key:
            return 1
    history: list[dict] = []
    cfg = load_collector_config()
    if cfg:
        _start_collector(cfg)
    print(clear_screen(), end="")
    print(render_welcome(collect_snapshot(settings), settings.llm_enabled))

    while True:
        try:
            raw = _read_line(prompt())
            raw = raw.strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Exit.")
            return 0

        if not raw:
            continue
        if raw in {"/exit", "exit", "quit", "/quit"}:
            return 0
        try:
            output = dispatch(raw, settings, history)
        except KeyboardInterrupt:
            output = "Interrupted."
        except Exception as exc:
            output = f"Error: {exc}"
        if output:
            cmd0 = raw.split()[0] if raw else ""
            if cmd0 == "/clear":
                print(clear_screen(), end="")
                print(render_welcome(collect_snapshot(settings), settings.llm_enabled))
            elif _is_panel_output(output):
                print("\n" + output)
            else:
                print(render_reply(output))
        if raw:
            _HISTORY.append(raw)
            if len(_HISTORY) > 100:
                _HISTORY.pop(0)


def dispatch(raw: str, settings: Settings | None = None, history: list[dict] | None = None) -> str:
    settings = settings or Settings.from_env()
    if raw.startswith("/"):
        return dispatch_command(raw, settings, history)
    return dispatch_natural(raw, settings, history)


def dispatch_command(raw: str, settings: Settings | None = None, history: list[dict] | None = None) -> str:
    settings = settings or Settings.from_env()
    parts = shlex.split(raw)
    command = parts[0]
    args = parts[1:]
    if command == "/help":
        return HELP
    if command == "/clear":
        if history is not None:
            history.clear()
        return "Conversation history cleared. Let's start a new one!"
    if command == "/stat":
        if args and args[0] == "help":
            return _STAT_HELP
        metric, period = _stat_args(args)
        return stat(settings, metric, period)
    if command == "/watch":
        if args and args[0] == "help":
            return _WATCH_HELP
        interval, metric = _watch_args(args)
        return watch(interval, settings, metric or None)
    if command in {"/cpu", "/memory", "/disk", "/swap", "/net", "/io"}:
        metric = command.removeprefix("/")
        return _stat_single(metric, settings)
    if command == "/top":
        if not args or args[0] == "help":
            return (
                "Top commands:\n"
                "  /top cpu    [N]   Top N processes by CPU usage\n"
                "  /top memory [N]   Top N processes by memory usage\n"
                "  /top disk   [N]   Disk partitions by usage\n"
                "  /top all    [N]   All of the above  (default: 5)"
            )
        metric, limit = _top_args(args)
        procs = _run_with_indicator("top", all_processes)
        disks = disk_info()
        return render_top(procs, disks, limit, metric)
    if command == "/docker":
        return _dispatch_docker(args, settings)
    if command == "/log":
        return _dispatch_log(args, settings)
    if command == "/service":
        if not args:
            return (
                "Service commands:\n"
                "  /service list      List all services\n"
                "  /service <name>    Show service status"
            )
        if args[0] == "list":
            result = _run_with_indicator("list_services", list_services)
            return render_service_list(result)
        svc = _run_with_indicator("service_status", service_status, args[0])
        return render_service(svc)
    if command == "/collect":
        return _dispatch_collect(args)
    if command == "/notify":
        return _dispatch_notify(args, settings)
    return f"Unknown command: {command}\nType /help to see available commands."


def dispatch_natural(raw: str, settings: Settings | None = None, history: list[dict] | None = None) -> str:
    settings = settings or Settings.from_env()

    # Detect natural language log search via @alias mention
    alias = _detect_log_alias(raw)
    if alias:
        # Always let the LLM handle @alias queries when a provider is enabled:
        # it understands intent (tail/search/errors) and calls the right tool,
        # and assistant.py renders the result with the same Rich panels as the
        # local path. Only fall back to local logic when the LLM is unavailable.
        if settings.llm_enabled:
            with Spinner(_llm_spinner_message(settings)):
                return answer(raw, settings, history)
        if _is_bare_alias_input(raw, alias):
            return (
                f"@{alias} 에 대해 무엇을 도와드릴까요?\n"
                f"  예: @{alias} 에러 확인 / @{alias} 마지막 50줄 보여줘"
            )
        return _log_search_natural(alias, raw)

    # Route all natural language to AI if a provider is enabled.
    if settings.llm_enabled:
        with Spinner(_llm_spinner_message(settings)):
            return answer(raw, settings, history)

    # Local fallback
    lowered = raw.lower()
    tokens = raw.split()
    if any(word in lowered for word in ("log", "logs")):
        path = next((token for token in tokens if token.startswith("/")), settings.log_file)
        return render_logs(tail_log(path, 80))
    if any(word in lowered for word in ("service", "systemd", "nginx", "apache", "mysql", "postgres", "redis")):
        service = infer_service_name(tokens)
        if service:
            return render_service(service_status(service))
    if any(word in lowered for word in ("process", "top")):
        return render_processes(top_processes(10))
    return local_answer(raw)


def _llm_spinner_message(settings: Settings) -> str:
    if settings.llm_provider == OPENAI_CODEX_PROVIDER:
        return "Asking OpenAI Codex..."
    return "Asking Gemini..."


_METRICS = {"cpu", "memory", "mem", "disk", "swap", "net", "network", "io"}

_STAT_HELP = (
    "Available metrics:\n"
    "  /stat all              Current full snapshot\n"
    "  /stat cpu              CPU + Load avg + per-core usage\n"
    "  /stat memory           Memory\n"
    "  /stat disk             Disk\n"
    "  /stat swap             Swap\n"
    "  /stat net              Network I/O\n"
    "  /stat io               Disk I/O\n"
    "\n"
    "Provide a period to view collected history:\n"
    "  /stat all 1d           History for last 1 day\n"
    "  /stat cpu 24h          History for last 24 hours\n"
    "  /stat all 2026-04-25   Specific date\n"
    "  /stat cpu 2026-04-24~2026-04-26  Date range"
)

_WATCH_HELP = (
    "Available metrics:\n"
    "  /watch all             Real-time full dashboard\n"
    "  /watch cpu             Real-time CPU + per-core usage\n"
    "  /watch memory          Real-time memory\n"
    "  /watch disk            Real-time disk\n"
    "  /watch swap            Real-time swap\n"
    "  /watch net             Real-time network I/O\n"
    "  /watch io              Real-time disk I/O\n"
    "\n"
    "  Update interval (sec) can be added at the end:\n"
    "  /watch all 2           Update dashboard every 2 seconds\n"
    "  /watch cpu 10          Update CPU every 10 seconds"
)


def _stat_args(args: list[str]) -> tuple[str | None, str | None]:
    metric = None
    period = None
    for a in args:
        if a.lower() == "all":
            metric = "all"
        elif a.lower() in _METRICS:
            metric = a.lower()
        else:
            period = a
    return metric, period


def _parse_period(s: str):
    import re
    from datetime import datetime, timedelta
    now = datetime.now()
    if "~" in s:
        left, right = s.split("~", 1)
        start = datetime.strptime(left.strip(), "%Y-%m-%d")
        end = datetime.strptime(right.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        return start, end, f"{left.strip()} ~ {right.strip()}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        start = datetime.strptime(s, "%Y-%m-%d")
        end = start.replace(hour=23, minute=59, second=59)
        return start, end, s
    days = _parse_duration_days(s)
    return now - timedelta(days=days), now, f"last {_fmt_duration(days)}"


def watch(interval: int, settings: Settings | None = None, metric: str | None = None) -> str:
    if not metric:
        return _WATCH_HELP
    settings = settings or Settings.from_env()
    interval = max(interval, 1)
    show_all = metric == "all"
    try:
        while True:
            print("\033[2J\033[H", end="")
            if show_all:
                print(_stat_all(settings))
            else:
                print(_stat_single(metric, settings))
            print(f"\n  [{metric}]  Refreshing every {interval}s. Ctrl-C to stop.")
            time.sleep(interval)
    except KeyboardInterrupt:
        return "watch stopped."


def stat(settings: Settings | None = None, metric: str | None = None, period: str | None = None) -> str:
    if not metric:
        return _STAT_HELP
    settings = settings or Settings.from_env()
    if period:
        return _stat_history(None if metric == "all" else metric, period)
    if metric == "all":
        return _stat_all(settings)
    return _stat_single(metric, settings)


def _stat_all(settings: Settings) -> str:
    return "\n".join([
        render_cpu(cpu_usage_percent(), load_average(), cpu_core_usage_percents()),
        render_memory(memory_info()),
        render_disk(disk_info()),
        render_swap(swap_info()),
        render_network(network_io()),
        render_disk_io(disk_io()),
    ])


def _stat_single(metric: str, settings: Settings) -> str:
    m = metric.lower()
    if m == "cpu":
        return render_cpu(cpu_usage_percent(), load_average(), cpu_core_usage_percents())
    if m in ("mem", "memory"):
        return render_memory(memory_info())
    if m == "disk":
        return render_disk(disk_info())
    if m == "swap":
        return render_swap(swap_info())
    if m in ("net", "network"):
        return render_network(network_io())
    if m == "io":
        return render_disk_io(disk_io())
    return f"Unknown metric: {metric}\nAvailable: all, cpu, memory, disk, swap, net, io"


def _stat_history(metric: str | None, period: str) -> str:
    cfg = load_collector_config()
    if not cfg:
        return "Collector is not configured.\nSet up with /collect set to start gathering data."
    try:
        start, end, label = _parse_period(period)
    except ValueError:
        return f"Invalid period format: {period}\nExamples: 1d, 24h, 2026-04-25, 2026-04-24~2026-04-26"
    records = load_history(cfg.folder, start, end)
    return render_history(records, metric, label)


_TOP_METRICS = {"cpu", "memory", "mem", "disk", "all"}


def _top_args(args: list[str]) -> tuple[str, int]:
    metric = "all"
    count = 5
    for a in args:
        al = a.lower()
        if al in _TOP_METRICS:
            metric = al
        else:
            try:
                count = int(a)
            except ValueError:
                pass
    return metric, count


def _watch_args(args: list[str]) -> tuple[int, str | None]:
    interval = 5
    metric = None
    for a in args:
        al = a.lower()
        if al == "all" or al in _METRICS:
            metric = al
        else:
            try:
                interval = int(a)
            except ValueError:
                pass
    return interval, metric


def _run_with_indicator(name: str, func, *args, **kwargs):
    print(render_tool_start(name), end="", flush=True)
    start = time.perf_counter()
    try:
        res = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"\r{render_tool_done(name, elapsed)}")
        return res
    except Exception:
        elapsed = time.perf_counter() - start
        print(f"\r{render_tool_fail(name, elapsed)}")
        raise


def main():
    _configure_terminal_output()
    parser = argparse.ArgumentParser(prog="monix")
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args", nargs="*", help="Arguments for the command")
    parser.add_argument("--version", action="version", version=f"monix {__version__}")
    parser.add_argument("--setup", action="store_true", help="Run LLM provider setup")
    parser.add_argument("--set-platform", action="store_true", help="Change platform setting")

    args = parser.parse_args()
    settings = Settings.from_env()

    if args.setup:
        _setup_llm_provider(settings)
        return 0

    if args.set_platform:
        _prompt_platform_setup(settings)
        return 0

    if not args.command:
        return repl(settings)

    full_raw = " ".join([args.command] + args.args)
    if full_raw.startswith("/"):
        print(render_reply(dispatch_command(full_raw, settings)))
    else:
        print(render_reply(dispatch_natural(full_raw, settings)))
    return 0


def _configure_terminal_output() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")


def _dispatch_docker(args: list[str], settings: Settings) -> str:  # noqa: ARG001
    if not args or args[0] == "help":
        return _docker_help()

    sub = args[0]

    # @alias lookup
    if sub.startswith("@"):
        alias = sub[1:]
        if not alias:
            return render_docker_aliases(registry.load())
        entry = registry.get(alias)
        if entry is None:
            return (
                f"Container alias not registered: @{alias}\n"
                f"  Register with: /docker add @{alias} <container>"
            )
        if entry.type != "docker":
            return f"@{alias} is not a docker type ({entry.type})\n  Use /log @{alias} instead."
        container = entry.container or ""
        err = _validate_flags(
            args[1:],
            frozenset({"-n", "--live", "--search"}),
            f"/docker @{alias} [-n N] [--search [pattern]] [--live]",
        )
        if err:
            return err
        if "--live" in args:
            return _docker_live(container, _get_opt(args, "-n", 20), settings)
        if "--search" in args:
            pattern = _get_str_opt(args, "--search")
            return render_log_search(search_container(container, pattern=pattern, lines=_get_opt(args, "-n", 0)))
        return render_logs(tail_container(container, _get_opt(args, "-n", 80)))

    if sub == "add":
        return _docker_add(args[1:])

    if sub == "ps":
        return render_docker_containers(list_containers())

    if sub == "list":
        return render_docker_aliases(registry.load())

    if sub in ("remove", "rm"):
        if len(args) < 2:
            return "Usage: /docker remove @alias"
        alias = args[1].lstrip("@")
        entry = registry.get(alias)
        if entry is not None and entry.type != "docker":
            return f"@{alias} is not a docker type. Use /log remove @{alias} instead."
        return f"@{alias} removed." if registry.remove(alias) else f"@{alias} not found."

    if sub == "logs":
        if len(args) < 2:
            return "Usage: /docker logs <container|@alias> [-n lines]"
        container, err = _resolve_docker_container(args[1])
        if err:
            return err
        err = _validate_flags(args[2:], frozenset({"-n"}), f"/docker logs {args[1]} [-n N]")
        if err:
            return err
        return render_logs(tail_container(container, _get_opt(args, "-n", 80)))

    if sub == "search":
        if len(args) < 2:
            return "Usage: /docker search <container|@alias> [pattern] [-n lines]"
        container, err = _resolve_docker_container(args[1])
        if err:
            return err
        err = _validate_flags(args[2:], frozenset({"-n"}), f"/docker search {args[1]} [pattern] [-n N]")
        if err:
            return err
        pattern_candidates = [a for a in args[2:] if not a.startswith("-")]
        pattern = pattern_candidates[0] if pattern_candidates else None
        return render_log_search(search_container(container, pattern=pattern, lines=_get_opt(args, "-n", 0)))

    if sub == "live":
        if len(args) < 2:
            return "Usage: /docker live <container|@alias> [-n lines]"
        container, err = _resolve_docker_container(args[1])
        if err:
            return err
        err = _validate_flags(args[2:], frozenset({"-n"}), f"/docker live {args[1]} [-n N]")
        if err:
            return err
        return _docker_live(container, _get_opt(args, "-n", 20), settings)

    if sub == "stats":
        target = args[1] if len(args) > 1 else None
        if target:
            resolved, err = _resolve_docker_container(target)
            if err:
                return err
            target = resolved
        stats = _run_with_indicator("docker_stats", container_stats, target)
        return render_docker_stats(stats)

    if sub == "top":
        if len(args) < 2:
            return "Usage: /docker top <container|@alias>"
        container, err = _resolve_docker_container(args[1])
        if err:
            return err
        result = _run_with_indicator("docker_top", container_processes, container)
        return render_docker_top(result)

    if sub == "inspect":
        if len(args) < 2:
            return "Usage: /docker inspect <container|@alias>"
        container, err = _resolve_docker_container(args[1])
        if err:
            return err
        info = _run_with_indicator("docker_inspect", container_inspect, container)
        return render_docker_inspect(info)

    return _docker_help()


def _resolve_docker_container(name: str) -> tuple[str, str | None]:
    """Return (container_name, None) or ("", error_message)."""
    if not name.startswith("@"):
        return name, None
    alias = name[1:]
    entry = registry.get(alias)
    if entry is None:
        return "", (
            f"Container alias not registered: {name}\n"
            f"  Register with: /docker add @{alias} <container>"
        )
    if entry.type != "docker":
        return "", f"@{alias} is not a docker type ({entry.type})"
    return entry.container or "", None


def _docker_add(args: list[str]) -> str:
    if not args or not args[0].startswith("@"):
        return "Usage: /docker add @alias <container>"
    alias = args[0][1:]
    if not alias:
        return "Please provide an alias. e.g.: /docker add @myapp myapp"
    positional = [a for a in args[1:] if not a.startswith("-")]
    container = positional[0] if positional else alias
    _, is_new = registry.add(alias, "docker", container=container)
    action = "Registered" if is_new else "Updated"
    return f"[{action}] Docker container: @{alias} -> {container}"


def _should_log_alert(sev: str, threshold: str) -> bool:
    if sev == "error":
        return True
    return sev == "warn" and threshold == "warn"


def _fire_log_webhook(err_buf, source: str, severity: str, settings: Settings) -> None:
    from monix.tools.notify import LogAlertConfig, NotifyConfig, send_log_alert
    if not settings.discord_webhook and not settings.slack_webhook:
        return
    send_log_alert(
        list(err_buf),
        source=source,
        severity=severity,
        config=NotifyConfig(
            discord_url=settings.discord_webhook,
            slack_url=settings.slack_webhook,
        ),
        log_config=LogAlertConfig(
            enabled=True,
            min_severity=settings.notify_log_severity,
            cooldown_seconds=settings.notify_log_cooldown,
        ),
    )


def _docker_live(container: str, n: int, settings: Settings) -> str:
    from collections import deque

    from monix.render import style
    from monix.tools.logs.app import classify_line

    source = f"docker://{container}"
    print(f"\n  {style('→', 'cyan')} {source}  Ctrl-C to stop\n")
    err_buf: deque = deque(maxlen=5)
    try:
        for line in follow_container(container, n):
            if line is None:
                break
            print("  " + colorize_log_line(line))
            if settings.notify_log_errors:
                sev = classify_line(line)
                if _should_log_alert(sev, settings.notify_log_severity):
                    err_buf.append(line)
                    _fire_log_webhook(err_buf, source, sev, settings)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        return f"Streaming error: {exc}"
    return "Stopped streaming."


def _docker_help() -> str:
    return (
        "Docker commands:\n"
        "  /docker ps                              List running containers\n"
        "  /docker stats [container]               Resource usage (CPU/mem/net/io)\n"
        "  /docker top <container>                 Processes inside a container\n"
        "  /docker inspect <container>             Ports, mounts, env, health\n"
        "  /docker add @alias <container>          Register container alias\n"
        "  /docker list                            List registered Docker aliases\n"
        "  /docker @alias [-n lines]               View registered container logs\n"
        "  /docker @alias --search [pattern]       Search error/pattern\n"
        "  /docker @alias --live [-n lines]        Real-time streaming\n"
        "  /docker remove @alias                   Unregister alias\n"
        "  /docker logs <container> [-n lines]     View container logs directly\n"
        "  /docker search <container> [pattern] [-n lines]  Search error/pattern (direct)\n"
        "  /docker live <container> [-n lines]     Real-time streaming (direct)"
    )


def _dispatch_log(args: list[str], settings: Settings) -> str:
    if not args or args[0] == "help":
        return _log_help()

    sub = args[0]

    # Direct path lookup
    raw_path: str | None = None
    if sub.startswith("@"):
        alias = sub[1:]
        if not alias:
            return render_log_aliases(registry.aliases())
        if alias.startswith("/") or alias.startswith("~"):
            raw_path = alias
        else:
            entry = registry.get(alias)
            if entry is None:
                known = registry.aliases()
                hint = "\n".join(f"  @{a}" for a in known) if known else "  (none)"
                return (
                    f"Log alias not registered: @{alias}\n\n"
                    f"Registered aliases:\n{hint}\n\n"
                    f"Use /log add @{alias} -app /path/to/file to register."
                )
            err = _validate_flags(
                args[1:],
                frozenset({"-n", "--live", "--search"}),
                f"/log @{alias} [-n N] [--search [pattern]] [--live]",
            )
            if err:
                return err
            n = _get_opt(args, "-n", 80)
            if "--live" in args:
                return _live_log(entry, n, settings)
            if "--search" in args:
                pattern = _get_str_opt(args, "--search")
                return _log_search_entry(entry, pattern, lines=_get_opt(args, "-n", 0))
            if entry.type == "docker":
                return render_logs(tail_container(entry.container or "", n))
            if entry.type == "nginx":
                return render_nginx_summary(tail_nginx_access(entry.path or "", n))
            return render_logs(tail_log(entry.path or "", n))
    elif sub.startswith("/") or sub.startswith("~"):
        raw_path = sub

    if raw_path is not None:
        err = _validate_flags(
            args[1:],
            frozenset({"-n", "--live"}),
            f"/log {raw_path} [-n N] [--live]",
        )
        if err:
            return err
        n = _get_opt(args, "-n", 80)
        if "--live" in args:
            from collections import deque

            from monix.render import style
            from monix.tools.logs.app import classify_line

            print(f"\n  {style('→', 'cyan')} {raw_path}  Ctrl-C to stop\n")
            err_buf: deque = deque(maxlen=5)
            try:
                for line in follow_log(raw_path, n):
                    if line is None:
                        break
                    print("  " + colorize_log_line(line))
                    if settings.notify_log_errors:
                        sev = classify_line(line)
                        if _should_log_alert(sev, settings.notify_log_severity):
                            err_buf.append(line)
                            _fire_log_webhook(err_buf, raw_path, sev, settings)
            except KeyboardInterrupt:
                pass
            except Exception as exc:
                return f"Streaming error: {exc}"
            return "Stopped streaming."
        return render_logs(tail_log(raw_path, n))

    if sub == "add":
        return _log_add(args[1:])

    if sub == "list":
        return render_log_list(registry.load())

    if sub in ("remove", "rm"):
        if len(args) < 2:
            return "Usage: /log remove @alias"
        alias = args[1].lstrip("@")
        return f"@{alias} removed." if registry.remove(alias) else f"@{alias} not found."

    return _log_help()


def _log_add(args: list[str]) -> str:
    if not args or not args[0].startswith("@"):
        return "Usage: /log add @alias -app /path/to/file"

    alias = args[0][1:]
    if not alias:
        return "Please provide an alias. e.g.: /log add @myapp -app /path/to/file"

    log_type = None
    for flag in ("-app", "-nginx", "-docker"):
        if flag in args:
            log_type = flag[1:]
            break

    if log_type is None:
        return (
            "Please specify log type:\n"
            "  -app     Application log\n"
            "  -nginx   Nginx log\n"
            "  -docker  Docker container log"
        )

    positional = [a for a in args[1:] if not a.startswith("-") and not a.startswith("@")]

    if log_type == "docker":
        container = positional[0] if positional else alias
        _, is_new = registry.add(alias, "docker", container=container)
        action = "Registered" if is_new else "Updated"
        return f"[{action}] Docker container: @{alias} -> {container}"

    if not positional:
        return f"Please provide file path.\nUsage: /log add @{alias} -{log_type} /path/to/file"

    path = positional[0]
    _, is_new = registry.add(alias, log_type, path=path)
    action = "Registered" if is_new else "Updated"
    return f"[{action}] {log_type} log: @{alias} -> {path}"


def _live_log(entry, initial_lines: int, settings: Settings) -> str:
    from collections import deque

    from monix.render import style
    from monix.tools.logs.app import classify_line

    if entry.type == "docker":
        container = entry.container or ""
        source = f"docker://{container}"
        print(f"\n  {style('→', 'cyan')} {source}  Ctrl-C to stop\n")
        gen = follow_container(container, initial_lines)
    else:
        path = entry.path or ""
        source = path
        print(f"\n  {style('→', 'cyan')} @{entry.alias}  {path}  Ctrl-C to stop\n")
        gen = follow_log(path, initial_lines)

    err_buf: deque = deque(maxlen=5)
    try:
        for line in gen:
            if line is None:
                break
            print("  " + colorize_log_line(line))
            if settings.notify_log_errors:
                sev = classify_line(line)
                if _should_log_alert(sev, settings.notify_log_severity):
                    err_buf.append(line)
                    _fire_log_webhook(err_buf, source, sev, settings)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        return f"Streaming error: {exc}"
    return "Stopped streaming."


def _log_help() -> str:
    return (
        "Log commands:\n"
        "  /log add @alias -app /path/to/file    Register app log\n"
        "  /log add @alias -nginx /path/to/file  Register Nginx log\n"
        "  /log add @alias -docker <container>   Register Docker container log\n"
        "  /log list                             List registered logs\n"
        "  /log @                                Show registered aliases\n"
        "  /log @alias [-n 100]                  View registered log\n"
        "  /log @alias --search [pattern]        Search error/warn (default: error filter)\n"
        "  /log @alias --live [-n 50]            Real-time log streaming\n"
        "  /log /path/to/file [-n 100]           Direct path view (no registration)\n"
        "  /log /path/to/file --live             Direct path real-time streaming\n"
        "  /log remove @alias                    Unregister alias"
    )


def _get_opt(args: list[str], flag: str, default: int) -> int:
    try:
        idx = args.index(flag)
        return int(args[idx + 1])
    except (ValueError, IndexError):
        return default


def _validate_flags(args: list[str], allowed: frozenset[str], usage: str) -> str | None:
    """Return an error message if args contain any flag not in `allowed`, else None."""
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("-"):
            if token not in allowed:
                hint = ", ".join(sorted(allowed)) if allowed else "none"
                return f"Invalid option: {token!r}\nUsage: {usage}\nValid options: {hint}"
            if token == "-n":
                if i + 1 >= len(args):
                    return f"Please provide a number after -n.\nUsage: {usage}"
                try:
                    int(args[i + 1])
                except ValueError:
                    return f"-n must be followed by a number: {args[i + 1]!r}\nUsage: {usage}"
                i += 2
                continue
            if token == "--search":
                if i + 1 < len(args) and not args[i + 1].startswith("-"):
                    i += 2
                    continue
        i += 1
    return None


def _int_arg(args: list[str], index: int, default: int) -> int:
    try:
        return int(args[index])
    except (IndexError, ValueError):
        return default


def _get_str_opt(args: list[str], flag: str) -> str | None:
    try:
        idx = args.index(flag)
        value = args[idx + 1]
        return value if not value.startswith("-") else None
    except (ValueError, IndexError):
        return None


# ── Natural language @alias log search ───────────────────────────────────────────

# Korean words MUST stay — direct commands like "@app 에러 확인" or "@app 마지막 50줄"
# should fast-path to local handling without a Gemini round-trip.
_ERROR_INTENTS = frozenset({
    "error", "errors", "exception", "exceptions", "fatal", "critical", "warn", "warning",
    "에러", "오류", "예외", "경고", "위험", "실패",
})

_TAIL_INTENTS = frozenset({
    "tail", "last", "latest", "show", "output", "display", "line", "lines", "recent",
    "마지막", "최근", "출력", "보여줘", "보여",
})

_LOG_SEARCH_INTENTS = frozenset({
    "search", "find", "check", "error", "errors", "look", "tell", "show", "verify",
})

# Korean tokens (조사/명사) MUST stay — Korean users write things like
# "@app 로그", "@app에서 확인" and the registered alias detector needs to treat
# the trailing Korean particles as stopwords, not as a search pattern.
_LOG_SEARCH_STOPWORDS = frozenset({
    "log", "logs", "the", "in", "for", "a", "an", "of", "with", "to", "is", "at",
    "see", "please", "if", "there", "are", "any", "be", "been", "was", "were",
    "me", "you", "it", "this", "that", "on", "and", "or", "but",
    "로그", "는", "을", "를", "에서", "의", "이", "가", "에", "로", "으로",
})

_ALL_LINES_KEYWORDS = frozenset({
    "all", "entire", "full", "whole",
})


def _detect_log_alias(text: str) -> str | None:
    """Return alias name if text contains @alias that exists in the registry."""
    import re as _re
    match = _re.search(r"@([a-zA-Z0-9_]+)", text)
    if not match:
        return None
    alias = match.group(1)
    return alias if registry.get(alias) is not None else None


def _is_bare_alias_input(text: str, alias: str) -> bool:
    """True if text is essentially just @alias with no actionable verb.

    "Bare" means: after stripping the alias token and pure stopwords,
    nothing remains.
    """
    skip = _LOG_SEARCH_STOPWORDS | {alias.lower(), f"@{alias.lower()}"}
    for token in text.split():
        clean = token.strip("@.,?!:;").lower()
        if not clean or clean in skip:
            continue
        return False
    return True


_ENGLISH_QUESTION_TOKENS = frozenset({
    "how", "what", "why", "where", "when", "who", "which",
    "can", "could", "would", "should", "is", "are", "do", "does",
    "please",
})

# Korean polite-ending question fragments MUST stay — Koreans frequently ask
# without a "?", e.g. "...있나요", "...해주세요". Routing depends on this so
# that natural-language questions defer to the LLM instead of bulk-tailing.
_KOREAN_QUESTION_FRAGMENTS = (
    "나요", "까요", "ㄴ가", "는가", "는지", "ㄹ까", "을까",
    "주세요", "주실래", "알려줘", "알려주", "보여줘", "보여주",
)


def _is_natural_question(text: str) -> bool:
    """True if the input looks like a natural-language question."""
    if "?" in text:
        return True
    if any(frag in text for frag in _KOREAN_QUESTION_FRAGMENTS):
        return True
    tokens = {t.strip(".,!:;").lower() for t in text.split()}
    return bool(tokens & _ENGLISH_QUESTION_TOKENS)


def _extract_search_pattern(text: str, alias: str) -> str | None:
    """Extract explicit search keyword from natural language."""
    import re as _re

    # 1. Quoted pattern: "timeout" or 'OOM'
    quoted = _re.search(r'["\'](.+?)["\']', text)
    if quoted:
        return quoted.group(1)

    # 2. Explicit @alias:pattern syntax, e.g. @application:warn
    colon = _re.search(
        rf'@{_re.escape(alias)}:([a-zA-Z0-9_\-\.]+)', text, _re.IGNORECASE,
    )
    if colon:
        return colon.group(1)

    # 3. Strip alias, stopwords, intent verbs, tail/error vocabulary; keep the rest
    skip = (
        _LOG_SEARCH_STOPWORDS
        | _LOG_SEARCH_INTENTS
        | _ERROR_INTENTS
        | _TAIL_INTENTS
        | _ALL_LINES_KEYWORDS
        | {alias.lower(), f"@{alias.lower()}"}
    )
    candidates = []
    for token in text.split():
        clean = token.strip("@.,?!:;").lower()
        if not clean or clean in skip:
            continue
        # Pure alphanumeric token (e.g. "timeout", "500")
        if _re.match(r"^[a-zA-Z0-9_\-\.]+$", clean):
            candidates.append(clean)

    return candidates[0] if candidates else None


def _log_search_entry(entry, pattern: str | None, lines: int = 0) -> str:
    """Run search on a log entry and render the result."""
    if entry.type == "docker":
        result = search_container(entry.container or "", pattern=pattern, lines=lines)
    else:
        result = search_log(entry.path or "", pattern=pattern, lines=lines)
    return render_log_search(result)


def _detect_log_intent(text: str) -> str:
    """Return 'search' or 'tail' based on keywords in the natural language text."""
    tokens = {t.strip("@.,?!:;").lower() for t in text.split()}
    if tokens & _ERROR_INTENTS:
        return "search"
    if tokens & _TAIL_INTENTS:
        return "tail"
    return "tail"


def _extract_lines_count(text: str, default: int = 80) -> int:
    """Extract line count from expressions like 'last 100 lines', 'tail 50'."""
    import re as _re
    m = _re.search(r"(?:last|tail|latest|-n)\s+(\d+)", text, _re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = _re.search(r"(\d+)\s*(?:lines?)", text, _re.IGNORECASE)
    if m:
        return int(m.group(1))
    return default


def _log_search_natural(alias: str, text: str) -> str:
    """Handle natural language log request triggered by @alias mention."""
    entry = registry.get(alias)
    if entry is None:
        return f"@{alias} log is not registered. Use /log add to register."

    intent = _detect_log_intent(text)

    if intent == "tail":
        n = _extract_lines_count(text, default=80)
        if entry.type == "docker":
            return render_logs(tail_container(entry.container or "", n))
        if entry.type == "nginx":
            return render_nginx_summary(tail_nginx_access(entry.path or "", n))
        return render_logs(tail_log(entry.path or "", n))

    # intent == "search"
    pattern = _extract_search_pattern(text, alias)
    tokens = {t.strip("@.,?!:;").lower() for t in text.split()}
    scan_lines = 999999 if tokens & _ALL_LINES_KEYWORDS else 2000
    return _log_search_entry(entry, pattern, lines=scan_lines)


def _parse_duration_days(s: str) -> float:
    """Convert '30s', '5m', '2h', '1d' to float days."""
    s = s.strip().lower()
    _units = {"s": 1 / 86400, "m": 1 / 1440, "h": 1 / 24, "d": 1.0}
    for suffix, factor in _units.items():
        if s.endswith(suffix):
            return float(s[:-1]) * factor
    try:
        return float(s)
    except ValueError:
        return 0.0


def _check_folder_writable(folder: str) -> str | None:
    """폴더 생성 및 쓰기 권한 검사. 문제 있으면 에러 메시지 반환, 없으면 None."""
    import os
    from pathlib import Path
    path = Path(folder).expanduser().resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return (
            f"Permission denied: cannot create '{path}'\n"
            f"  Fix: sudo mkdir -p {path} && sudo chown $USER:$USER {path}"
        )
    except OSError as exc:
        return f"Cannot create folder '{path}': {exc}"
    if not os.access(path, os.W_OK):
        return (
            f"Permission denied: no write access to '{path}'\n"
            f"  Fix: sudo chown $USER:$USER {path}"
        )
    return None


def _fmt_duration(days: float) -> str:
    """Format float days to a human-readable string."""
    seconds = days * 86400
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{days:.1f}d"


def _dispatch_collect(args: list[str]) -> str:
    if not args or args[0] == "help":
        return (
            "Collector commands:\n"
            "  /collect list                    Show current configuration\n"
            "  /collect set <interval> <retention> <folder>  Set/Update collector\n"
            "  /collect remove                  Disable and remove collector\n"
            "\n"
            "  Units: s(sec), m(min), h(hour), d(day) — default is d\n"
            "  e.g.) /collect set 1h 30d /path/to/folder"
        )

    sub = args[0]

    if sub == "list":
        cfg = load_collector_config()
        if not cfg:
            return "Collector is not configured. Use /collect set to configure."
        active = _collector_thread is not None and _collector_thread.is_alive()
        status = "Active" if active else "Stopped"
        lines = [
            f"Collector configuration [{status}]",
            f"  Interval:   {_fmt_duration(cfg.interval_days)}",
            f"  Retention:  {_fmt_duration(cfg.retention_days)}",
            f"  Storage:    {cfg.folder}",
        ]
        if _collector_last_saved:
            lines.append(f"  Last saved: {_collector_last_saved}")
        if _collector_last_error:
            lines.append(f"  Last error: {_collector_last_error}")
        return "\n".join(lines)

    if sub == "set":
        rest = args[1:]
        if len(rest) < 3:
            return (
                "Usage: /collect set <interval> <retention> <folder>\n"
                "  e.g.) /collect set 1h 30d /path/to/folder"
            )
        try:
            interval = _parse_duration_days(rest[0])
            retention = _parse_duration_days(rest[1])
        except ValueError:
            return "Invalid interval or retention values.\n  e.g.) /collect set 1h 30d /path/to/folder"
        if interval <= 0 or retention <= 0:
            return "Interval and retention must be greater than 0."
        folder = rest[2]
        folder_err = _check_folder_writable(folder)
        if folder_err:
            return folder_err
        cfg = CollectorConfig(interval_days=interval, retention_days=retention, folder=folder)
        save_collector_config(cfg)
        _start_collector(cfg)
        return (
            f"Collector configured and started\n"
            f"  Interval:   {_fmt_duration(interval)}\n"
            f"  Retention:  {_fmt_duration(retention)}\n"
            f"  Storage:    {folder}"
        )

    if sub == "remove":
        from monix.tools.collect import CONFIG_PATH
        _collector_stop.set()
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        return "Collector configuration removed."

    return f"Unknown subcommand: {sub}\nType /collect to see available commands."


def _dispatch_notify(args: list[str], settings: Settings) -> str:
    # Reload to pick up any changes made via /notify set
    settings = Settings.from_env()

    if not args or args[0] in ("help", "--help"):
        return (
            "Notify commands:\n"
            "  /notify set <option> <value>   Configure webhook settings (stored in ~/.monix/notify_config.json)\n"
            "  /notify test [discord|slack]   Send a test alert to the specified webhook (both if omitted)\n"
            "  /notify status                 Show effective webhook configuration and last sent times\n"
            "\n"
            "Metric alert options (/notify set ...):\n"
            "  discord <url|off>              Discord webhook URL\n"
            "  slack <url|off>                Slack webhook URL\n"
            "  cpu on|off                     Toggle CPU threshold alerts\n"
            "  memory on|off                  Toggle memory threshold alerts\n"
            "  disk on|off                    Toggle disk threshold alerts\n"
            "  cooldown <seconds>             Cooldown between repeated metric alerts (default: 3600)\n"
            "\n"
            "Log error alert options (/notify set ...):\n"
            "  log-errors on|off              Toggle log error webhook alerts (default: off)\n"
            "  log-severity error|warn        Minimum severity to alert on (default: error)\n"
            "  log-cooldown <seconds>         Cooldown between repeated log alerts (default: 300)\n"
            "\n"
            "Environment variables (overridden by /notify set):\n"
            "  MONIX_DISCORD_WEBHOOK=<url>         Discord webhook URL\n"
            "  MONIX_SLACK_WEBHOOK=<url>            Slack webhook URL\n"
            "  MONIX_NOTIFY_COOLDOWN=3600           Metric alert cooldown (default: 1h)\n"
            "  MONIX_NOTIFY_CPU/MEM/DISK=1          Toggle metric alerts (0 to disable)\n"
            "  MONIX_NOTIFY_LOG_ERRORS=0            Enable log error alerts (default: 0=off)\n"
            "  MONIX_NOTIFY_LOG_SEVERITY=error      Min log severity: error|warn\n"
            "  MONIX_NOTIFY_LOG_COOLDOWN=300        Log alert cooldown in seconds"
        )

    sub = args[0]

    if sub == "set":
        return _dispatch_notify_set(args[1:])

    if sub == "test":
        target = args[1] if len(args) > 1 else "all"
        return _notify_test(target, settings)

    if sub == "status":
        return _notify_status(settings)

    return f"Unknown /notify subcommand: {sub}\nType /notify help to see available commands."


def _dispatch_notify_set(args: list[str]) -> str:
    from monix.tools.notify.config_store import load_notify_config, set_notify_field, reset_notify_config

    if not args:
        cfg = load_notify_config()
        if not cfg:
            return (
                "No settings configured via /notify set.\n"
                "Using environment variables only.\n\n"
                "Usage:\n"
                "  /notify set discord <url|off>           Set/unset Discord webhook URL\n"
                "  /notify set slack <url|off>             Set/unset Slack webhook URL\n"
                "  /notify set cpu on|off                  Toggle CPU alerts\n"
                "  /notify set memory on|off               Toggle memory alerts\n"
                "  /notify set disk on|off                 Toggle disk alerts\n"
                "  /notify set cooldown <seconds>          Set cooldown (default: 3600)\n"
                "  /notify set log-errors on|off           Toggle log error alerts\n"
                "  /notify set log-severity error|warn     Set minimum log severity\n"
                "  /notify set log-cooldown <seconds>      Set log alert cooldown (default: 300)\n"
                "  /notify set reset                       Clear all stored settings"
            )
        lines = ["Stored notify settings (override env vars):"]
        if "discord_url" in cfg:
            url = cfg["discord_url"]
            lines.append(f"  discord:  {url[:40] + '...' if url and len(url) > 40 else url or 'off'}")
        if "slack_url" in cfg:
            url = cfg["slack_url"]
            lines.append(f"  slack:    {url[:40] + '...' if url and len(url) > 40 else url or 'off'}")
        if "cooldown" in cfg:
            lines.append(f"  cooldown: {cfg['cooldown']}s")
        if "cpu" in cfg:
            lines.append(f"  cpu:      {'on' if cfg['cpu'] else 'off'}")
        if "memory" in cfg:
            lines.append(f"  memory:   {'on' if cfg['memory'] else 'off'}")
        if "disk" in cfg:
            lines.append(f"  disk:       {'on' if cfg['disk'] else 'off'}")
        if "log_errors" in cfg:
            lines.append(f"  log-errors: {'on' if cfg['log_errors'] else 'off'}")
        if "log_severity" in cfg:
            lines.append(f"  log-sev:    {cfg['log_severity']}")
        if "log_cooldown" in cfg:
            lines.append(f"  log-cd:     {cfg['log_cooldown']}s")
        lines.append("\nRun /notify status to see the effective (merged) configuration.")
        return "\n".join(lines)

    sub = args[0]

    if sub == "reset":
        reset_notify_config()
        return "All stored /notify set settings cleared. Environment variables will be used."

    if sub in ("discord", "slack"):
        if len(args) < 2:
            return f"Usage: /notify set {sub} <url|off>"
        val = args[1]
        key = "discord_url" if sub == "discord" else "slack_url"
        if val.lower() == "off":
            set_notify_field(key, None)
            return f"{sub.title()} webhook URL cleared."
        set_notify_field(key, val)
        return f"{sub.title()} webhook URL saved. Run /notify test {sub} to verify."

    if sub in ("cpu", "memory", "disk"):
        if len(args) < 2 or args[1].lower() not in ("on", "off"):
            return f"Usage: /notify set {sub} on|off"
        enabled = args[1].lower() == "on"
        set_notify_field(sub, enabled)
        return f"{sub.title()} alerts {'enabled' if enabled else 'disabled'}."

    if sub == "cooldown":
        if len(args) < 2:
            return "Usage: /notify set cooldown <seconds>"
        try:
            secs = int(args[1])
        except ValueError:
            return f"Invalid cooldown value: {args[1]!r}  (must be an integer)"
        if secs < 0:
            return "Cooldown must be 0 or greater."
        set_notify_field("cooldown", secs)
        return f"Cooldown set to {secs}s."

    if sub == "log-errors":
        if len(args) < 2 or args[1].lower() not in ("on", "off"):
            return "Usage: /notify set log-errors on|off"
        enabled = args[1].lower() == "on"
        set_notify_field("log_errors", enabled)
        return f"Log error alerts {'enabled' if enabled else 'disabled'}."

    if sub == "log-severity":
        if len(args) < 2 or args[1].lower() not in ("error", "warn"):
            return "Usage: /notify set log-severity error|warn"
        set_notify_field("log_severity", args[1].lower())
        return f"Log alert minimum severity set to '{args[1].lower()}'."

    if sub == "log-cooldown":
        if len(args) < 2:
            return "Usage: /notify set log-cooldown <seconds>"
        try:
            secs = int(args[1])
        except ValueError:
            return f"Invalid log-cooldown value: {args[1]!r}  (must be an integer)"
        if secs < 0:
            return "Log cooldown must be 0 or greater."
        set_notify_field("log_cooldown", secs)
        return f"Log alert cooldown set to {secs}s."

    return (
        f"Unknown setting: {sub!r}\n"
        "Available: discord, slack, cpu, memory, disk, cooldown, log-errors, log-severity, log-cooldown, reset"
    )


def _notify_test(target: str, settings: Settings) -> str:
    from monix.tools.notify import send_alert, NotifyConfig, AlertFilter

    if target not in ("discord", "slack", "all"):
        return f"Unknown target: {target}\nUsage: /notify test [discord|slack]"

    config = NotifyConfig(
        discord_url=settings.discord_webhook if target in ("discord", "all") else None,
        slack_url=settings.slack_webhook if target in ("slack", "all") else None,
        cooldown_seconds=0,
        alert_filter=AlertFilter(cpu=True, memory=True, disk=True),
    )

    if not config.get("discord_url") and not config.get("slack_url"):
        return (
            "No webhook URL configured for the selected target.\n"
            "Set MONIX_DISCORD_WEBHOOK or MONIX_SLACK_WEBHOOK in your environment."
        )

    import platform as _platform
    host = _platform.node() or "unknown"
    test_alerts = ["CPU usage is high: 91.0% >= 85.0% (test message)"]

    failed = send_alert(test_alerts, host, config)
    if not failed:
        sent = []
        if config.get("discord_url"):
            sent.append("Discord")
        if config.get("slack_url"):
            sent.append("Slack")
        return f"Test alert sent to: {', '.join(sent)}"
    return f"Webhook delivery failed: {', '.join(failed)}"


def _notify_status(settings: Settings) -> str:
    from monix.tools.notify.webhook import _post_json as _  # noqa: F401 — ensure module loads
    from pathlib import Path
    import json

    state_path = Path.home() / ".monix" / "notify_state.json"
    try:
        state: dict = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}

    def _fmt_url(url: str | None) -> str:
        if not url:
            return "not set"
        return url[:40] + "..." if len(url) > 40 else url

    lines = [
        "Notify configuration",
        f"  Discord webhook:    {_fmt_url(settings.discord_webhook)}",
        f"  Slack webhook:      {_fmt_url(settings.slack_webhook)}",
        f"  Cooldown:           {settings.notify_cooldown}s",
        f"  CPU alerts:         {'on' if settings.notify_cpu else 'off'}",
        f"  Memory alerts:      {'on' if settings.notify_mem else 'off'}",
        f"  Disk alerts:        {'on' if settings.notify_disk else 'off'}",
        f"  Log error alerts:   {'on' if settings.notify_log_errors else 'off'}",
        f"  Log min severity:   {settings.notify_log_severity}",
        f"  Log cooldown:       {settings.notify_log_cooldown}s",
    ]
    if state:
        lines.append(f"  Last sent state: {state_path}")
        lines.append(f"  Tracked keys:    {len(state)}")
    else:
        lines.append("  Last sent state: (no alerts sent yet)")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
