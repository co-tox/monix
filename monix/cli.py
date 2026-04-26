from __future__ import annotations

import argparse
import shlex
import sys
import time

from monix import __version__
from monix.config import Settings
from monix.core.assistant import answer, infer_service_name, local_answer
from monix.picker import NO_ARG_COMMANDS, pick
from monix.tools.logs import follow_log, registry, search_log, tail_log
from monix.tools.logs.docker import follow_container, list_containers, tail_container
from monix.tools.logs.nginx import tail_nginx_access
from monix.tools.services import service_status
from monix.tools.system import collect_snapshot, top_processes
from monix.render import (
    clear_screen,
    colorize_log_line,
    prompt,
    render_docker_containers,
    render_log_aliases,
    render_log_list,
    render_log_search,
    render_logs,
    render_nginx_summary,
    render_reply,
    render_processes,
    render_service,
    render_snapshot,
    render_welcome,
)


HELP = """Commands:
  /status                          서버 상태 (CPU, 메모리, 디스크, 알림)
  /watch [seconds]                 실시간 모니터링 (Ctrl-C로 종료)
  /top [limit]                     CPU 상위 프로세스
  /log add @alias -app <path>      앱 로그 등록
  /log add @alias -nginx <path>    Nginx 로그 등록
  /log add @alias -docker <name>   Docker 컨테이너 로그 등록
  /log list                        등록된 로그 목록
  /log docker-list                 실행 중인 Docker 컨테이너 목록
  /log @                           등록된 alias 보기
  /log @alias [-n lines]           등록된 로그 보기
  /log @alias --search [pattern]   에러/경고 검색 (pattern 생략 시 에러 필터)
  /log @alias --live [-n lines]    등록된 로그 실시간 스트리밍
  /log /path/to/file [-n lines]    경로 직접 지정 (등록 불필요)
  /log /path/to/file --live        경로 직접 실시간 스트리밍
  /log remove @alias               로그 등록 해제
  /logs [path] [lines]             로그 직접 보기 (기존)
  /service <name>                  systemd 서비스 상태
  /ask <question>                  Gemini에게 질문 (GEMINI_API_KEY 필요)
  /clear                           대화 기록 초기화
  /help                            도움말
  /exit                            종료

자연어로도 바로 물어볼 수 있어요:
  "CPU 왜 이렇게 높아?"  "nginx 서비스 확인해줘"  "메모리 언제 부족해질까?"
  "@api 로그에서 에러 확인해줘"  "@nginx timeout 찾아줘"\""""


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
    print(render_welcome(collect_snapshot(settings), settings.gemini_enabled))
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
        return render_snapshot(collect_snapshot(settings))
    if command == "/watch":
        interval = _int_arg(args, 0, 5)
        return watch(interval, settings)
    if command == "/top":
        limit = _int_arg(args, 0, 10)
        return render_processes(top_processes(limit))
    if command == "/log":
        return _dispatch_log(args, settings)
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

    # @alias 자연어 로그 검색 감지 — "@api 에러 확인해줘" 같은 형태 처리
    alias = _detect_log_alias(raw)
    if alias:
        return _log_search_natural(alias, raw)

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
    "error", "errors", "exception", "fatal", "critical",
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


def _detect_log_alias(text: str) -> str | None:
    """Return alias name if text contains @alias that exists in the registry."""
    import re as _re
    match = _re.search(r"@(\w+)", text)
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
        # Keep ASCII alphanumeric tokens that look like keywords (e.g. "500", "timeout")
        if _re.match(r"^[a-zA-Z0-9_\-\.]+$", clean):
            candidates.append(clean)

    return candidates[0] if candidates else None


def _log_search_entry(entry, pattern: str | None, lines: int = 500) -> str:
    """Run search_log or docker equivalent and render the result."""
    if entry.type == "docker":
        raw = tail_container(entry.container or "", lines)
        all_lines = raw.get("lines", [])
        import re as _re
        from monix.tools.logs.app import classify_line
        if pattern is not None:
            try:
                compiled = _re.compile(pattern, _re.IGNORECASE)
            except _re.error:
                compiled = _re.compile(_re.escape(pattern), _re.IGNORECASE)
            matches = [
                {"lineno": i + 1, "line": l, "severity": classify_line(l)}
                for i, l in enumerate(all_lines) if compiled.search(l)
            ]
        else:
            matches = [
                {"lineno": i + 1, "line": l, "severity": classify_line(l)}
                for i, l in enumerate(all_lines) if classify_line(l) != "normal"
            ]
        result = {
            "path": f"docker://{entry.container}",
            "status": raw["status"],
            "query": pattern,
            "total_scanned": len(all_lines),
            "matches": matches,
        }
    else:
        result = search_log(entry.path or "", pattern=pattern, lines=lines)
    return render_log_search(result)


def _detect_log_intent(text: str) -> str:
    """Return 'search' or 'tail' based on keywords in the natural language text.

    Rules (in priority order):
    1. Explicit error keywords (에러, 오류, error …)  → 'search'
    2. Explicit tail keywords (마지막, 최근, 출력 …) without error words → 'tail'
    3. Default → 'tail'  (safer: showing lines is more useful than empty results)
    """
    tokens = {t.strip("@.,?!:；。").lower() for t in text.split()}
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
    return _log_search_entry(entry, pattern)


if __name__ == "__main__":
    sys.exit(main())
