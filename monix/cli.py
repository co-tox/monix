from __future__ import annotations

import argparse
import shlex
import sys
import time

from monix import __version__
from monix.config import Settings
from monix.core.assistant import answer, infer_service_name, local_answer
from monix.picker import NO_ARG_COMMANDS, pick
from monix.tools.logs import tail_log
from monix.tools.processes import top_processes
from monix.tools.services import service_status
from monix.tools.system import collect_snapshot
from monix.render import clear_screen, prompt, render_logs, render_reply, render_processes, render_service, render_snapshot, render_welcome


HELP = """Commands:
  /status                 서버 상태 (CPU, 메모리, 디스크, 알림)
  /watch [seconds]        실시간 모니터링 (Ctrl-C로 종료)
  /top [limit]            CPU 상위 프로세스
  /logs [path] [lines]    로그 파일 보기
  /service <name>         systemd 서비스 상태
  /ask <question>         Gemini에게 질문 (GEMINI_API_KEY 필요)
  /clear                  대화 기록 초기화
  /help                   도움말
  /exit                   종료

자연어로도 바로 물어볼 수 있어요:
  "CPU 왜 이렇게 높아?"  "nginx 서비스 확인해줘"  "메모리 언제 부족해질까?\""""


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"monix {__version__}")
        return 0
    if args.command == "status":
        print(render_snapshot(collect_snapshot(settings.thresholds)))
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
    print(render_welcome(collect_snapshot(settings.thresholds), settings.gemini_enabled))
    while True:
        try:
            raw = input(prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not raw:
            continue

        if raw == "/":
            raw = _pick_and_fill()
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
        return render_snapshot(collect_snapshot(settings.thresholds))
    if command == "/watch":
        interval = _int_arg(args, 0, 5)
        return watch(interval, settings)
    if command == "/top":
        limit = _int_arg(args, 0, 10)
        return render_processes(top_processes(limit))
    if command == "/logs":
        path = args[0] if args else settings.log_file
        lines = _int_arg(args, 1, 80)
        return render_logs(tail_log(path, lines))
    if command == "/service":
        if not args:
            return "사용법: /service <name>"
        return render_service(service_status(args[0]))
    if command == "/ask":
        if not args:
            return "사용법: /ask <question>"
        return answer(" ".join(args), settings, history)
    return f"알 수 없는 명령입니다: {command}\n/help를 입력해 사용 가능한 명령을 확인하세요."


def dispatch_natural(raw: str, settings: Settings | None = None, history: list[dict] | None = None) -> str:
    settings = settings or Settings.from_env()

    # Gemini 활성화 시 모든 자연어를 AI로 라우팅 (Claude처럼)
    if settings.gemini_enabled:
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
            print(render_snapshot(collect_snapshot(settings.thresholds)))
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


def _int_arg(args: list[str], index: int, default: int) -> int:
    try:
        return int(args[index])
    except (IndexError, ValueError):
        return default


if __name__ == "__main__":
    sys.exit(main())
