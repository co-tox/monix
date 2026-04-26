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
from monix.tools.logs import follow_log, registry, search_log, tail_log
from monix.tools.logs.docker import follow_container, list_containers, search_container, tail_container
from monix.tools.services import service_status
from monix.tools.logs.nginx import tail_nginx_access
from monix.render import (
    clear_screen,
    colorize_log_line,
    prompt,
    render_docker_aliases,
    render_docker_containers,
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
    render_processes,
    render_service,
    render_snapshot,
    render_stat,
    render_swap,
    render_tool_done,
    render_tool_fail,
    render_tool_start,
    render_welcome,
)
from monix.tools.system import (
    collect_snapshot,
    cpu_usage_percent,
    disk_info,
    disk_io,
    load_average,
    memory_info,
    network_io,
    swap_info,
    top_processes,
)


HELP = """Commands:
  /stat [cpu|memory|disk|swap|net|io]  단발 스냅샷 (인자 없으면 전체)
  /watch [cpu|memory|disk|swap|net|io] [seconds]  실시간 모니터링 (기본 5s, Ctrl-C로 종료)
  /log add @alias -app <path>      앱 로그 등록
  /log add @alias -nginx <path>    Nginx 로그 등록
  /log add @alias -docker <name>   Docker 컨테이너 로그 등록
  /log list                        등록된 로그 목록
  /log @alias [-n lines]           등록된 로그 보기
  /log @alias --search [pattern]   에러/경고 검색 (pattern 생략 시 에러 필터)
  /log @alias --live [-n lines]    등록된 로그 실시간 스트리밍
  /log /path/to/file [-n lines]    경로 직접 지정 (등록 불필요)
  /log /path/to/file --live        경로 직접 실시간 스트리밍
  /log remove @alias               로그 등록 해제

  /docker ps                       실행 중인 컨테이너 목록
  /docker add @alias <container>   컨테이너 alias 등록
  /docker list                     등록된 Docker alias 목록
  /docker @alias [-n lines]        등록된 컨테이너 로그 보기
  /docker @alias --search [pat]    에러/패턴 검색
  /docker @alias --live            실시간 스트리밍
  /docker remove @alias            alias 해제
  /docker logs <container>         컨테이너 로그 직접 보기 [-n lines]
  /docker search <container>       에러/패턴 검색 (직접) [pattern] [-n lines]
  /docker live <container>         실시간 스트리밍 (직접) [-n lines]

  /logs [path] [lines]             로그 직접 보기 (기존)
  /ask <question>                  Gemini에게 질문 (GEMINI_API_KEY 필요)
  /clear                           대화 기록 초기화
  /help                            도움말
  /exit                            종료

자연어로도 바로 물어볼 수 있어요:
  "CPU 왜 이렇게 높아?"  "nginx 서비스 확인해줘"  "메모리 언제 부족해질까?"
  "@api 로그에서 에러 확인해줘"  "@nginx timeout 찾아줘"\""""


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
    if args.command == "cpu":
        print(render_cpu(cpu_usage_percent(), load_average()))
        return 0
    if args.command == "memory":
        print(render_memory(memory_info()))
        return 0
    if args.command == "disk":
        print(render_disk(disk_info()))
        return 0
    if args.command == "swap":
        print(render_swap(swap_info()))
        return 0
    if args.command == "net":
        print(render_network(network_io()))
        return 0
    if args.command == "io":
        print(render_disk_io(disk_io()))
        return 0
    if args.command == "stat":
        print(stat(settings, getattr(args, "metric", None)))
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

    subparsers.add_parser("cpu", help="show CPU usage and load average")
    subparsers.add_parser("memory", help="show memory usage")
    subparsers.add_parser("disk", help="show disk usage")
    subparsers.add_parser("swap", help="show swap usage")
    subparsers.add_parser("net", help="show network I/O")
    subparsers.add_parser("io", help="show disk I/O read/write rates")
    stat_parser = subparsers.add_parser("stat", help="comprehensive one-shot snapshot (cpu/mem/disk/swap/net/io)")
    stat_parser.add_argument("metric", nargs="?", help="cpu|memory|disk|swap|net|io")

    stat_parser = subparsers.add_parser("stat", help="one-shot snapshot (cpu/memory/disk/swap/net/io)")
    stat_parser.add_argument("metric", nargs="?", help="cpu|memory|disk|swap|net|io")

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
            output = "Interrupted. / 중단했습니다."
        except Exception as exc:
            output = f"Error: {exc} / 오류: {exc}"
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
    if command == "/stat":
        metric = args[0] if args else None
        return stat(settings, metric)
    if command == "/cpu":
        return render_cpu(cpu_usage_percent(), load_average())
    if command == "/memory":
        return render_memory(memory_info())
    if command == "/disk":
        return render_disk(disk_info())
    if command == "/swap":
        return render_swap(swap_info())
    if command == "/net":
        return render_network(network_io())
    if command == "/io":
        return render_disk_io(disk_io())
    if command == "/watch":
        interval, metric = _watch_args(args)
        return watch(interval, settings, metric)
    if command == "/top":
        limit = _int_arg(args, 0, 10)
        procs = _run_with_indicator("top_processes", top_processes, limit)
        return render_processes(procs)
    if command == "/docker":
        return _dispatch_docker(args, settings)
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

    # @alias 자연어 로그 검색 감지 — "@api 에러 확인해줘" 같은 형태 처리
    alias = _detect_log_alias(raw)
    if alias:
        return _log_search_natural(alias, raw)

    # Gemini 활성화 시 모든 자연어를 AI로 라우팅 (Claude처럼)
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


def watch(interval: int, settings: Settings | None = None, metric: str | None = None) -> str:
    settings = settings or Settings.from_env()
    interval = max(interval, 2)
    try:
        while True:
            snapshot, swap, net, io = _collect_all(settings)
            print("\033[2J\033[H", end="")
            if metric:
                print(_stat_single(metric, settings))
            else:
                print(render_snapshot(collect_snapshot(settings)))
            label = f"  [{metric}]" if metric else ""
            print(f"\nRefreshing every {interval}s{label}. Press Ctrl-C to stop.")
            time.sleep(interval)
    except KeyboardInterrupt:
        return "watch를 종료했습니다."


def stat(settings: Settings | None = None, metric: str | None = None) -> str:
    settings = settings or Settings.from_env()
    if metric:
        return _stat_single(metric, settings)
    parts = [
        render_cpu(cpu_usage_percent(), load_average()),
        render_memory(memory_info()),
        render_disk(disk_info()),
        render_swap(swap_info()),
        render_network(network_io()),
        render_disk_io(disk_io()),
    ]
    return "\n".join(parts)


def _stat_single(metric: str, settings: Settings) -> str:
    m = metric.lower()
    if m == "cpu":
        return render_cpu(cpu_usage_percent(), load_average())
    if m in ("memory", "mem"):
        return render_memory(memory_info())
    if m == "disk":
        return render_disk(disk_info())
    if m == "swap":
        return render_swap(swap_info())
    if m in ("net", "network"):
        return render_network(network_io())
    if m == "io":
        return render_disk_io(disk_io())
    return f"알 수 없는 메트릭: {metric}\n사용 가능: cpu, memory, disk, swap, net, io"


def _watch_args(args: list[str]) -> tuple[int, str | None]:
    interval = 5
    metric = None
    for a in args:
        try:
            interval = int(a)
        except ValueError:
            metric = a
    return interval, metric


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


def _dispatch_docker(args: list[str], settings: Settings) -> str:  # noqa: ARG001
    if not args:
        return _docker_help()

    sub = args[0]

    # @alias 조회
    if sub.startswith("@"):
        alias = sub[1:]
        if not alias:
            return render_docker_aliases(registry.load())
        entry = registry.get(alias)
        if entry is None:
            return (
                f"등록된 컨테이너가 없습니다: @{alias}\n"
                f"  /docker add @{alias} <container> 로 등록하세요."
            )
        if entry.type != "docker":
            return f"@{alias} 는 docker 타입이 아닙니다. ({entry.type})\n  /log @{alias} 로 접근하세요."
        container = entry.container or ""
        if "--live" in args:
            return _docker_live(container, _get_opt(args, "-n", 20))
        if "--search" in args:
            pattern = _get_str_opt(args, "--search")
            return render_log_search(search_container(container, pattern=pattern, lines=_get_opt(args, "-n", 500)))
        return render_logs(tail_container(container, _get_opt(args, "-n", 80)))

    if sub == "add":
        return _docker_add(args[1:])

    if sub == "ps":
        return render_docker_containers(list_containers())

    if sub == "list":
        return render_docker_aliases(registry.load())

    if sub in ("remove", "rm"):
        if len(args) < 2:
            return "사용법: /docker remove @alias"
        alias = args[1].lstrip("@")
        entry = registry.get(alias)
        if entry is not None and entry.type != "docker":
            return f"@{alias} 는 docker 타입이 아닙니다. /log remove @{alias} 를 사용하세요."
        return f"@{alias} 제거 완료." if registry.remove(alias) else f"@{alias} 를 찾을 수 없습니다."

    if sub == "logs":
        if len(args) < 2:
            return "사용법: /docker logs <container|@alias> [-n lines]"
        container, err = _resolve_docker_container(args[1])
        if err:
            return err
        return render_logs(tail_container(container, _get_opt(args, "-n", 80)))

    if sub == "search":
        if len(args) < 2:
            return "사용법: /docker search <container|@alias> [pattern] [-n lines]"
        container, err = _resolve_docker_container(args[1])
        if err:
            return err
        pattern_candidates = [a for a in args[2:] if not a.startswith("-")]
        pattern = pattern_candidates[0] if pattern_candidates else None
        return render_log_search(search_container(container, pattern=pattern, lines=_get_opt(args, "-n", 500)))

    if sub == "live":
        if len(args) < 2:
            return "사용법: /docker live <container|@alias> [-n lines]"
        container, err = _resolve_docker_container(args[1])
        if err:
            return err
        return _docker_live(container, _get_opt(args, "-n", 20))

    return _docker_help()


def _resolve_docker_container(name: str) -> tuple[str, str | None]:
    """Return (container_name, None) or ("", error_message).

    If name starts with '@', looks up the alias in registry and returns its
    container. Otherwise passes the name through unchanged.
    """
    if not name.startswith("@"):
        return name, None
    alias = name[1:]
    entry = registry.get(alias)
    if entry is None:
        return "", (
            f"등록된 컨테이너가 없습니다: {name}\n"
            f"  /docker add @{alias} <container> 로 등록하세요."
        )
    if entry.type != "docker":
        return "", f"@{alias} 는 docker 타입이 아닙니다. ({entry.type})"
    return entry.container or "", None


def _docker_add(args: list[str]) -> str:
    if not args or not args[0].startswith("@"):
        return "사용법: /docker add @alias <container>"
    alias = args[0][1:]
    if not alias:
        return "alias를 입력해주세요. 예: /docker add @myapp myapp"
    positional = [a for a in args[1:] if not a.startswith("-")]
    container = positional[0] if positional else alias
    _, is_new = registry.add(alias, "docker", container=container)
    action = "등록" if is_new else "업데이트"
    return f"[{action}] Docker 컨테이너: @{alias} → {container}"


def _docker_live(container: str, n: int) -> str:
    from monix.render import style
    print(f"\n  {style('→', 'cyan')} docker://{container}  Ctrl-C to stop / Ctrl-C 로 종료\n")
    try:
        for line in follow_container(container, n):
            if line is None:
                break
            print("  " + colorize_log_line(line))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        return f"Streaming error: {exc} / 스트리밍 오류: {exc}"
    return "Stopped streaming. / 스트리밍을 종료했습니다."


def _docker_help() -> str:
    return (
        "Docker 명령어:\n"
        "  /docker ps                              실행 중인 컨테이너 목록\n"
        "  /docker add @alias <container>          컨테이너 등록\n"
        "  /docker list                            등록된 Docker alias 목록\n"
        "  /docker @alias [-n lines]               등록된 컨테이너 로그 보기\n"
        "  /docker @alias --search [pattern]       에러/패턴 검색\n"
        "  /docker @alias --live [-n lines]        실시간 스트리밍\n"
        "  /docker remove @alias                   등록 해제\n"
        "  /docker logs <container> [-n lines]     컨테이너 로그 직접 보기\n"
        "  /docker search <container> [pattern]    에러/패턴 검색 (직접)\n"
        "  /docker live <container> [-n lines]     실시간 스트리밍 (직접)"
    )


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
                hint = "\n".join(f"  @{a}" for a in known) if known else "  (none)"
                return (
                    f"Log not registered: @{alias} / 등록된 로그가 없습니다: @{alias}\n\n"
                    f"Registered aliases:\n{hint}\n\n"
                    f"Use /log add @{alias} -app /path/to/file to register."
                )
            n = _get_opt(args, "-n", 80)
            if "--live" in args:
                return _live_log(entry, n)
            if "--search" in args:
                pattern = _get_str_opt(args, "--search")
                return _log_search_entry(entry, pattern, lines=_get_opt(args, "-n", 500))
            if entry.type == "docker":
                return render_logs(tail_container(entry.container or "", n))
            if entry.type == "nginx":
                return render_nginx_summary(tail_nginx_access(entry.path or "", n))
            return render_logs(tail_log(entry.path or "", n))
    elif sub.startswith("/") or sub.startswith("~"):
        raw_path = sub

    if raw_path is not None:
        n = _get_opt(args, "-n", 80)
        if "--live" in args:
            from monix.render import style
            print(f"\n  {style('→', 'cyan')} {raw_path}  Ctrl-C to stop / Ctrl-C 로 종료\n")
            try:
                for line in follow_log(raw_path, n):
                    if line is None:
                        break
                    print("  " + colorize_log_line(line))
            except KeyboardInterrupt:
                pass
            except Exception as exc:
                return f"Streaming error: {exc} / 스트리밍 오류: {exc}"
            return "Stopped streaming. / 스트리밍을 종료했습니다."
        return render_logs(tail_log(raw_path, n))

    if sub == "add":
        return _log_add(args[1:])

    if sub == "list":
        return render_log_list(registry.load())

    if sub == "docker-list":
        return render_docker_containers(list_containers())

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
        print(f"\n  {style('→', 'cyan')} docker://{container}  Ctrl-C to stop / Ctrl-C 로 종료\n")
        gen = follow_container(container, initial_lines)
    else:
        path = entry.path or ""
        print(f"\n  {style('→', 'cyan')} @{entry.alias}  {path}  Ctrl-C to stop / Ctrl-C 로 종료\n")
        gen = follow_log(path, initial_lines)

    try:
        for line in gen:
            if line is None:
                break
            print("  " + colorize_log_line(line))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        return f"Streaming error: {exc} / 스트리밍 오류: {exc}"
    return "Stopped streaming. / 스트리밍을 종료했습니다."


def _log_help() -> str:
    return (
        "로그 명령어:\n"
        "  /log add @alias -app /path/to/file    앱 로그 등록\n"
        "  /log add @alias -nginx /path/to/file  Nginx 로그 등록\n"
        "  /log add @alias -docker <container>   Docker 컨테이너 로그 등록\n"
        "  /log list                             등록된 로그 목록\n"
        "  /log docker-list                      실행 중인 Docker 컨테이너 목록\n"
        "  /log @                                등록된 alias 보기\n"
        "  /log @alias [-n 100]                  등록된 로그 보기\n"
        "  /log @alias --search [pattern]        에러/경고 검색 (pattern 생략 시 에러 필터)\n"
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


def _get_str_opt(args: list[str], flag: str) -> str | None:
    try:
        idx = args.index(flag)
        value = args[idx + 1]
        return value if not value.startswith("-") else None
    except (ValueError, IndexError):
        return None


# ── 자연어 @alias 로그 검색 ────────────────────────────────────────────────────

# 에러/패턴 검색 인텐트 — 이 단어가 있으면 search_log 로 라우팅
_ERROR_INTENTS = frozenset({
    "에러", "에러가", "에러있어", "오류", "오류가", "있는지", "있나", "있어",
    "경고", "경고가",
    "error", "errors", "exception", "fatal", "critical", "warn", "warning",
})

# tail(보기) 인텐트 — 에러 인텐트보다 약하며, 에러 인텐트가 없을 때 tail 로 라우팅
_TAIL_INTENTS = frozenset({
    "마지막", "최근", "끝", "tail", "last", "latest",
    "보여줘", "보여", "출력해줘", "출력", "표시", "나와", "줄", "라인", "line", "lines",
})

_LOG_SEARCH_INTENTS = frozenset({
    "검색", "검색해줘", "검색해서", "찾아줘", "찾아", "확인해줘", "확인",
    "에러", "에러가", "에러있어", "오류", "오류가", "봐줘", "봐", "알려줘",
    "보여줘", "있는지", "있나", "있어", "체크", "체크해줘",
    "error", "errors", "check", "search", "find",
})

_LOG_SEARCH_STOPWORDS = frozenset({
    "로그", "를", "을", "에서", "에", "의", "로", "은", "는", "이",
    "해줘", "줘", "log", "logs", "the", "in", "for", "a", "an",
})

_ALL_LINES_KEYWORDS = frozenset({
    "전체", "모두", "전부", "all", "entire", "full", "whole",
})


def _detect_log_alias(text: str) -> str | None:
    """Return alias name if text contains @alias that exists in the registry."""
    import re as _re
    match = _re.search(r"@([a-zA-Z0-9_]+)", text)
    if not match:
        return None
    alias = match.group(1)
    return alias if registry.get(alias) is not None else None


def _extract_search_pattern(text: str, alias: str) -> str | None:
    """Extract explicit search keyword from natural language.

    Looks for quoted strings first, then non-Korean alphanum tokens that
    survive stopword filtering.  Returns None when only error-intent words
    are present (→ caller uses error/warn filter instead).
    """
    import re as _re

    # 1. Quoted pattern: "timeout" or 'OOM'
    quoted = _re.search(r'["\'](.+?)["\']', text)
    if quoted:
        return quoted.group(1)

    # 2. Strip @alias token, stopwords, and pure-intent words, keep the rest
    skip = _LOG_SEARCH_STOPWORDS | _LOG_SEARCH_INTENTS | {alias, f"@{alias}"}
    tokens = text.split()
    candidates = []
    for token in tokens:
        clean = token.strip("@.,?!:；。").lower()
        if clean in skip or not clean:
            continue
        # Pure ASCII alphanumeric token (e.g. "timeout", "500")
        if _re.match(r"^[a-zA-Z0-9_\-\.]+$", clean):
            candidates.append(clean)
            continue
        # Mixed token with ASCII prefix (e.g. "WARN로그만" → "warn")
        ascii_prefix = _re.match(r"^([a-zA-Z][a-zA-Z0-9_]*)(?=[^a-zA-Z0-9_])", clean)
        if ascii_prefix:
            prefix = ascii_prefix.group(1)
            if prefix not in skip:
                candidates.append(prefix)

    return candidates[0] if candidates else None


def _log_search_entry(entry, pattern: str | None, lines: int = 500) -> str:
    """Run search on a log entry and render the result."""
    if entry.type == "docker":
        result = search_container(entry.container or "", pattern=pattern, lines=lines)
    else:
        result = search_log(entry.path or "", pattern=pattern, lines=lines)
    return render_log_search(result)


def _detect_log_intent(text: str) -> str:
    """Return 'search' or 'tail' based on keywords in the natural language text.

    Rules (in priority order):
    1. Explicit error keywords (에러, 오류, error, warn …)  → 'search'
    2. Explicit tail keywords (마지막, 최근, 출력 …) without error words → 'tail'
    3. Default → 'tail'  (safer: showing lines is more useful than empty results)
    """
    import re as _re
    tokens: set[str] = set()
    for t in text.split():
        clean = t.strip("@.,?!:；。").lower()
        tokens.add(clean)
        # Extract ASCII prefix from mixed tokens (e.g. "WARN로그만" → "warn")
        ascii_m = _re.match(r"^([a-z][a-z0-9_]*)(?=[^a-z0-9_])", clean)
        if ascii_m:
            tokens.add(ascii_m.group(1))
    if tokens & _ERROR_INTENTS:
        return "search"
    if tokens & _TAIL_INTENTS:
        return "tail"
    return "tail"


def _extract_lines_count(text: str, default: int = 80) -> int:
    """Extract line count from expressions like '마지막 100줄', 'last 50 lines', '-n 200'."""
    import re as _re
    # "마지막 N줄" or "최근 N줄" or "N줄" or "last N lines" or "-n N"
    m = _re.search(r"(?:마지막|최근|last|tail|-n)\s+(\d+)", text, _re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = _re.search(r"(\d+)\s*(?:줄|라인|lines?)", text, _re.IGNORECASE)
    if m:
        return int(m.group(1))
    return default


def _log_search_natural(alias: str, text: str) -> str:
    """Handle natural language log request triggered by @alias mention."""
    entry = registry.get(alias)
    if entry is None:
        return f"@{alias} 로그가 등록되어 있지 않습니다. /log add 로 등록하세요."

    intent = _detect_log_intent(text)

    if intent == "tail":
        n = _extract_lines_count(text, default=80)
        if entry.type == "docker":
            return render_logs(tail_container(entry.container or "", n))
        if entry.type == "nginx":
            from monix.tools.logs.nginx import tail_nginx_access
            return render_nginx_summary(tail_nginx_access(entry.path or "", n))
        return render_logs(tail_log(entry.path or "", n))

    # intent == "search"
    pattern = _extract_search_pattern(text, alias)
    tokens = {t.strip("@.,?!:；。").lower() for t in text.split()}
    scan_lines = 999999 if tokens & _ALL_LINES_KEYWORDS else 2000
    return _log_search_entry(entry, pattern, lines=scan_lines)


if __name__ == "__main__":
    sys.exit(main())
