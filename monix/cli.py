from __future__ import annotations

import argparse
import itertools
import shlex
import sys
import threading
import time

from monix import __version__
from monix.config import Settings
from monix.core.assistant import answer, infer_service_name, local_answer
from monix.picker import NO_ARG_COMMANDS, pick, pick_with_filter
from monix.tools.logs import follow_log, registry, tail_log
from monix.tools.logs.docker import follow_container, tail_container
from monix.tools.services import service_status
from monix.render import (
    clear_screen,
    colorize_log_line,
    prompt,
    render_log_aliases,
    render_log_list,
    render_logs,
    render_reply,
    render_processes,
    render_service,
    render_snapshot,
    render_welcome,
    render_memory,
    render_disk,
    render_cpu,
    render_tool_done,
    render_tool_fail,
    render_tool_start,
)
from monix.tools.system import collect_snapshot, cpu_usage_percent, disk_info, load_average, memory_info, top_processes


HELP = """Commands:
  /status                          서버 상태 (CPU, 메모리, 디스크, 알림)
  /watch [seconds]                 실시간 모니터링 (Ctrl-C로 종료)
  /log add @alias -app <path>      앱 로그 등록
  /log add @alias -docker <name>   Docker 컨테이너 로그 등록
  /log @                           등록된 alias 보기
  /log @alias [-n lines]           등록된 로그 보기
  /log @alias --live [-n lines]    등록된 로그 실시간 스트리밍
  /log /path/to/file --live        경로 직접 실시간 스트리밍
  /logs [path] [lines]             로그 직접 보기 (기존)
  /service <name>                  systemd 서비스 상태
  /clear                           대화 기록 초기화
  /help                            도움말
  /exit                            종료
  /ask <question>                  Gemini에게 질문 (GEMINI_API_KEY 필요)
  /log remove @alias               로그 등록 해제
  /log /path/to/file [-n lines]    경로 직접 지정 (등록 불필요)
  /log list                        등록된 로그 목록
  /log add @alias -nginx <path>    Nginx 로그 등록
  /top [limit]                     CPU 상위 프로세스
  /memory                 메모리 사용량 상세
  /disk                   디스크 사용량
  /cpu                    CPU 사용률 + Load average

자연어로도 바로 물어볼 수 있어요:
  "CPU 왜 이렇게 높아?"  "nginx 서비스 확인해줘"  "메모리 언제 부족해질까?\""""


_HISTORY: list[str] = []


def _read_line(prompt_str: str) -> str:
    """readline/input 기반 입력. 한글 IME와 좌우 이동을 유지하고 '/' 단독 입력 시 피커를 연다."""
    try:
        import readline as _rl
    except ImportError:
        _rl = None

    if _rl is not None:
        existing = {_rl.get_history_item(i) for i in range(1, _rl.get_current_history_length() + 1)}
        for entry in _HISTORY:
            if entry and entry not in existing:
                _rl.add_history(entry)

    raw = input(prompt_str)
    if raw.strip() != "/":
        return raw

    selected = pick_with_filter() or pick()
    if not selected:
        return ""
    if selected in NO_ARG_COMMANDS:
        return selected

    if _rl is None:
        return selected

    _rl.set_startup_hook(lambda: _rl.insert_text(selected + " "))
    try:
        full = input(prompt()).strip()
    finally:
        _rl.set_startup_hook(None)
    return full or selected


class Spinner:
    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str = "") -> None:
        self._message = message
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r  {frame}  {self._message}")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def __enter__(self) -> "Spinner":
        if sys.stdout.isatty():
            self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()


def _run_with_indicator(label: str, fn, *args, **kwargs):
    if not sys.stdout.isatty():
        return fn(*args, **kwargs)
    print(render_tool_start(label))
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        sys.stdout.write(f"\033[A\r\033[K{render_tool_done(label, time.time() - t0)}\n")
        sys.stdout.flush()
        return result
    except Exception:
        sys.stdout.write(f"\033[A\r\033[K{render_tool_fail(label, time.time() - t0)}\n")
        sys.stdout.flush()
        raise


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"monix {__version__}")
        return 0
    if args.command == "status":
        print(render_snapshot(collect_snapshot(settings)))
        return 0
    if args.command == "cpu":
        print(render_cpu(cpu_usage_percent(), load_average()))
        return 0
    if args.command == "memory":
        print(render_memory(memory_info()))
        return 0
    if args.command == "disk":
        print(render_disk(disk_info()))
        return 0
    if args.command == "top":
        print(render_processes(top_processes(args.limit)))
        return 0
    if args.command == "logs":
        print(render_logs(tail_log(args.path or settings.log_file, args.lines)))
        return 0
    if args.command == "service":
        print(render_service(service_status(args.name)))
        return 0
    if args.command == "ask":
        print(answer(args.question, settings))
        return 0
    return repl(settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="monix", description="Gemini-powered server monitoring CLI")
    parser.add_argument("--version", action="store_true", help="show version")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="show server status")
    subparsers.add_parser("cpu", help="show CPU usage and load average")
    subparsers.add_parser("memory", help="show memory usage")
    subparsers.add_parser("disk", help="show disk usage")

    top_parser = subparsers.add_parser("top", help="show top CPU processes")
    top_parser.add_argument("--limit", "-n", type=int, default=10)

    logs_parser = subparsers.add_parser("logs", help="tail a log file")
    logs_parser.add_argument("path", nargs="?")
    logs_parser.add_argument("--lines", "-n", type=int, default=80)

    service_parser = subparsers.add_parser("service", help="show systemd service status")
    service_parser.add_argument("name")

    ask_parser = subparsers.add_parser("ask", help="ask Gemini for analysis")
    ask_parser.add_argument("question", nargs="+")

    return parser


def repl(settings: Settings | None = None) -> int:
    settings = settings or Settings.from_env()
    history: list[dict] = []
    print(clear_screen(), end="")
    print(render_welcome(collect_snapshot(settings), settings.gemini_enabled))
    while True:
        try:
            raw = _read_line(prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not raw:
            continue

        if raw in {"/exit", "exit", "quit", "/quit"}:
            return 0
        try:
            output = dispatch(raw, settings, history)
        except KeyboardInterrupt:
            output = "중단했습니다."
        except Exception as exc:
            output = f"오류: {exc}"
        if output:
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
        return "대화 기록을 초기화했습니다. 새로운 대화를 시작해요!"
    if command == "/status":
        snap = _run_with_indicator("snapshot", collect_snapshot, settings)
        return render_snapshot(snap)
    if command == "/cpu":
        return render_cpu(cpu_usage_percent(), load_average())
    if command == "/memory":
        return render_memory(memory_info())
    if command == "/disk":
        return render_disk(disk_info())
    if command == "/watch":
        interval = _int_arg(args, 0, 5)
        return watch(interval, settings)
    if command == "/top":
        limit = _int_arg(args, 0, 10)
        procs = _run_with_indicator("top_processes", top_processes, limit)
        return render_processes(procs)
    if command == "/log":
        return _dispatch_log(args, settings)
    if command == "/logs":
        path = args[0] if args else settings.log_file
        lines = _int_arg(args, 1, 80)
        log = _run_with_indicator("tail_log", tail_log, path, lines)
        return render_logs(log)
    if command == "/service":
        if not args:
            return "사용법: /service <name>"
        svc = _run_with_indicator("service_status", service_status, args[0])
        return render_service(svc)
    if command == "/ask":
        if not args:
            return "사용법: /ask <question>"
        with Spinner("Gemini에 질문 중..."):
            return answer(" ".join(args), settings, history)
    return f"알 수 없는 명령입니다: {command}\n/help를 입력해 사용 가능한 명령을 확인하세요."


def dispatch_natural(raw: str, settings: Settings | None = None, history: list[dict] | None = None) -> str:
    settings = settings or Settings.from_env()

    if settings.gemini_enabled:
        with Spinner("Gemini에 질문 중..."):
            return answer(raw, settings, history)

    # Local fallback
    lowered = raw.lower()
    tokens = raw.split()
    if any(word in lowered for word in ("로그", "log")):
        path = next((token for token in tokens if token.startswith("/")), settings.log_file)
        return render_logs(tail_log(path, 80))
    if any(word in lowered for word in ("서비스", "service", "systemd", "nginx", "apache", "mysql", "postgres", "redis")):
        service = infer_service_name(tokens)
        if service:
            return render_service(service_status(service))
    if any(word in lowered for word in ("프로세스", "process", "top")):
        return render_processes(top_processes(10))
    return local_answer(raw)


def watch(interval: int, settings: Settings | None = None) -> str:
    settings = settings or Settings.from_env()
    interval = max(interval, 1)
    try:
        while True:
            print("\033[2J\033[H", end="")
            print(render_snapshot(collect_snapshot(settings)))
            print(f"\nRefreshing every {interval}s. Press Ctrl-C to stop.")
            time.sleep(interval)
    except KeyboardInterrupt:
        return "watch를 종료했습니다."


def _pick_and_fill() -> str:
    """피커로 명령어를 고르고, 인자가 필요한 명령어는 readline으로 이어서 입력받는다."""
    selected = pick()
    if not selected:
        return ""
    if selected in NO_ARG_COMMANDS:
        return selected
    # 인자 입력 필요 — readline으로 명령어 pre-fill 후 이어서 입력
    try:
        import readline as _rl
        _cmd = selected + " "
        _rl.set_startup_hook(lambda: _rl.insert_text(_cmd))
        try:
            raw = input(prompt()).strip()
        finally:
            _rl.set_startup_hook(None)
        return raw or selected
    except ImportError:
        return selected


def _dispatch_log(args: list[str], settings: Settings) -> str:
    if not args:
        return _log_help()

    sub = args[0]

    # Direct path: "/log /path/to/file" or "/log @/path/to/file" or "/log ~/path"
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
                hint = "\n".join(f"  @{a}" for a in known) if known else "  (없음)"
                return (
                    f"등록된 로그가 없습니다: @{alias}\n\n"
                    f"등록된 alias:\n{hint}\n\n"
                    f"/log add @{alias} -app /path/to/file 로 등록하세요."
                )
            n = _get_opt(args, "-n", 80)
            if "--live" in args:
                return _live_log(entry, n)
            result = tail_container(entry.container or "", n) if entry.type == "docker" else tail_log(entry.path or "", n)
            return render_logs(result)
    elif sub.startswith("/") or sub.startswith("~"):
        raw_path = sub

    if raw_path is not None:
        n = _get_opt(args, "-n", 80)
        if "--live" in args:
            from monix.render import style
            print(f"\n  {style('→', 'cyan')} {raw_path}  Ctrl-C 로 종료\n")
            try:
                for line in follow_log(raw_path, n):
                    print("  " + colorize_log_line(line))
            except KeyboardInterrupt:
                pass
            except Exception as exc:
                return f"스트리밍 오류: {exc}"
            return "스트리밍을 종료했습니다."
        return render_logs(tail_log(raw_path, n))

    if sub == "add":
        return _log_add(args[1:])

    if sub == "list":
        return render_log_list(registry.load())

    if sub in ("remove", "rm"):
        if len(args) < 2:
            return "사용법: /log remove @alias"
        alias = args[1].lstrip("@")
        return f"@{alias} 제거 완료." if registry.remove(alias) else f"@{alias} 를 찾을 수 없습니다."

    return _log_help()


def _log_add(args: list[str]) -> str:
    if not args or not args[0].startswith("@"):
        return "사용법: /log add @alias -app /path/to/file"

    alias = args[0][1:]
    if not alias:
        return "alias를 입력해주세요. 예: /log add @myapp -app /path/to/file"

    log_type = None
    for flag in ("-app", "-nginx", "-docker"):
        if flag in args:
            log_type = flag[1:]
            break

    if log_type is None:
        return (
            "로그 타입을 지정해주세요:\n"
            "  -app     애플리케이션 로그\n"
            "  -nginx   Nginx 로그\n"
            "  -docker  Docker 컨테이너 로그"
        )

    positional = [a for a in args[1:] if not a.startswith("-") and not a.startswith("@")]

    if log_type == "docker":
        container = positional[0] if positional else alias
        _, is_new = registry.add(alias, "docker", container=container)
        action = "등록" if is_new else "업데이트"
        return f"[{action}] Docker 컨테이너: @{alias} → {container}"

    if not positional:
        return f"파일 경로를 입력해주세요.\n사용법: /log add @{alias} -{log_type} /path/to/file"

    path = positional[0]
    _, is_new = registry.add(alias, log_type, path=path)
    action = "등록" if is_new else "업데이트"
    return f"[{action}] {log_type} 로그: @{alias} → {path}"


def _live_log(entry, initial_lines: int) -> str:
    from monix.render import style

    if entry.type == "docker":
        container = entry.container or ""
        print(f"\n  {style('→', 'cyan')} docker://{container}  Ctrl-C 로 종료\n")
        gen = follow_container(container, initial_lines)
    else:
        path = entry.path or ""
        print(f"\n  {style('→', 'cyan')} @{entry.alias}  {path}  Ctrl-C 로 종료\n")
        gen = follow_log(path, initial_lines)

    try:
        for line in gen:
            print("  " + colorize_log_line(line))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        return f"스트리밍 오류: {exc}"
    return "스트리밍을 종료했습니다."


def _log_help() -> str:
    return (
        "로그 명령어:\n"
        "  /log add @alias -app /path/to/file    앱 로그 등록\n"
        "  /log add @alias -nginx /path/to/file  Nginx 로그 등록\n"
        "  /log add @alias -docker <container>   Docker 컨테이너 로그 등록\n"
        "  /log list                             등록된 로그 목록\n"
        "  /log @                                등록된 alias 보기\n"
        "  /log @alias [-n 100]                  등록된 로그 보기\n"
        "  /log @alias --live [-n 50]            등록된 로그 실시간 스트리밍\n"
        "  /log /path/to/file [-n 100]           경로 직접 지정 (등록 불필요)\n"
        "  /log /path/to/file --live             경로 직접 실시간 스트리밍\n"
        "  /log remove @alias                    등록 해제"
    )


def _get_opt(args: list[str], flag: str, default: int) -> int:
    try:
        idx = args.index(flag)
        return int(args[idx + 1])
    except (ValueError, IndexError):
        return default


def _int_arg(args: list[str], index: int, default: int) -> int:
    try:
        return int(args[index])
    except (IndexError, ValueError):
        return default


if __name__ == "__main__":
    sys.exit(main())
