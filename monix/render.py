from __future__ import annotations

import os
import re
import shutil
import sys

from monix import __version__
from monix.tools.system import human_bytes

_LOG_ERROR_RE = re.compile(r"\b(ERROR|FATAL|CRITICAL|Exception|Traceback)\b", re.IGNORECASE)
_LOG_WARN_RE = re.compile(r"\b(WARN|WARNING)\b", re.IGNORECASE)


_MASCOT = [
    r"  /\_/\  ",
    r" ( o . o)",
    r"  > Gemini <",
    r"  ~(___)-",
]


def render_welcome(snapshot: dict, gemini_enabled: bool) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    mode = badge("Gemini AI", "green") if gemini_enabled else badge("Local monitor", "yellow")
    alerts = snapshot.get("alerts") or []
    alert_text = badge(f"{len(alerts)} alert(s)", "red") if alerts else badge("healthy", "green")
    disk = (snapshot.get("disks") or [{}])[0]
    memory = snapshot.get("memory", {})

    mascot_lines = [_text(style(line, "cyan"), inner) for line in _MASCOT]

    lines = [
        _rule(width, "top"),
        *mascot_lines,
        _rule(width, "mid"),
        _text(f"{style('Monix', 'bold')} {style('server monitor', 'muted')}  v{__version__}  {mode}", inner),
        _text(f"{style('Host', 'cyan')} {snapshot.get('host', 'unknown')}  {style(snapshot.get('os', ''), 'muted')}", inner),
        _rule(width, "mid"),
        _metric("CPU", snapshot.get("cpu_percent"), inner),
        _metric("Memory", memory.get("percent"), inner, suffix=f"{human_bytes(memory.get('available'))} free"),
        _metric("Disk /", disk.get("percent"), inner, suffix=f"{human_bytes(disk.get('free'))} free"),
        _line("Load", _load(snapshot.get("load_average")), inner),
        _line("Status", alert_text, inner),
        _rule(width, "mid"),
        _text(f"{style('뭐든 물어봐!', 'bold')}  CPU 상태 봐줘    nginx 왜 느려?    메모리 분석해줘", inner),
        _text(f"{style('/help', 'cyan')} 명령 목록   {style('/clear', 'cyan')} 대화 초기화   {style('/watch 5', 'cyan')} 실시간   {style('/exit', 'cyan')} 종료", inner),
        _rule(width, "bottom"),
    ]
    return "\n".join(lines)


def render_reply(body: str) -> str:
    prefix = style("◆", "cyan") + " "
    lines = body.splitlines() or [""]
    result = [prefix + lines[0]]
    for line in lines[1:]:
        result.append("  " + line)
    return "\n" + "\n".join(result)


def render_panel(title: str, body: str) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    lines = [_rule(width, "top"), _text(style(title, "bold"), inner), _rule(width, "mid")]
    for line in body.splitlines() or [""]:
        lines.append(_text(colorize_line(line), inner))
    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_snapshot(snapshot: dict) -> str:
    lines = [
        f"Host: {snapshot['host']}",
        f"OS: {snapshot['os']}",
        f"Time: {snapshot['time']}",
        f"Uptime: {snapshot['uptime']}",
        f"CPU: {_percent(snapshot.get('cpu_percent'))}",
        f"Load avg: {_load(snapshot.get('load_average'))}",
        f"Memory: {_memory(snapshot.get('memory', {}))}",
        "Disk:",
    ]
    for disk in snapshot.get("disks", []):
        lines.append(
            f"  {disk['path']}: {_percent(disk.get('percent'))} used, "
            f"{human_bytes(disk.get('free'))} free / {human_bytes(disk.get('total'))}"
        )
    alerts = snapshot.get("alerts") or []
    lines.append("Alerts:")
    if alerts:
        lines.extend(f"  - {alert}" for alert in alerts)
    else:
        lines.append("  none")
    lines.append("Top processes:")
    lines.extend(f"  {line}" for line in _process_lines(snapshot.get("top_processes", [])))
    return "\n".join(lines)


def render_processes(processes: list[dict]) -> str:
    return "\n".join([style("PID      CPU%   MEM%   COMMAND", "bold"), *_process_lines(processes)])


def render_logs(result: dict) -> str:
    status_color = "green" if result["status"] == "ok" else "red"
    header = f"Log: {result['path']} {badge(result['status'], status_color)}"
    if result["status"] != "ok":
        return header
    return "\n".join([header, *(colorize_log_line(line) for line in result["lines"])])


def render_log_list(entries: list) -> str:
    if not entries:
        return "등록된 로그가 없습니다.\n  /log add @alias -app /path/to/file 로 등록하세요."
    rows = [style(f"{'ALIAS':<22} {'TYPE':<8} PATH / CONTAINER", "bold")]
    for e in entries:
        target = e.path or e.container or "(없음)"
        rows.append(f"@{e.alias:<21} {e.type:<8} {target}")
    return "\n".join(rows)


def render_log_aliases(alias_list: list[str]) -> str:
    if not alias_list:
        return "등록된 로그가 없습니다. /log add 로 등록하세요."
    return "\n".join(["등록된 로그 (alias):", *(f"  @{a}" for a in alias_list)])


def colorize_log_line(line: str) -> str:
    if _LOG_ERROR_RE.search(line):
        return style(line, "red")
    if _LOG_WARN_RE.search(line):
        return style(line, "yellow")
    return line


def render_log_search(result: dict) -> str:
    path = result["path"]
    status = result["status"]

    if status != "ok":
        return f"Log 검색: {path} {badge(status, 'red')}"

    query = result.get("query")
    total = result.get("total_scanned", 0)
    matches: list[dict] = result.get("matches", [])

    query_label = f'패턴 "{query}"' if query else "에러/경고"
    error_count = sum(1 for m in matches if m["severity"] == "error")
    warn_count = sum(1 for m in matches if m["severity"] == "warn")
    found_color = "red" if error_count else "yellow" if warn_count else "green"
    found_text = f"{len(matches)}건 발견" if matches else "이상 없음"

    lines = [
        f"Log: {path}",
        f"{style(query_label, 'cyan')} 검색 — 스캔 {total:,}줄  {badge(found_text, found_color)}",
    ]

    if not matches:
        return "\n".join(lines)

    lines.append("")
    for m in matches:
        color = "red" if m["severity"] == "error" else "yellow"
        lineno_str = f"L{m['lineno']:>5}"
        lines.append(f"  {style(lineno_str, 'muted')}  {style(m['line'], color)}")

    lines += [
        "",
        f"  에러 {style(str(error_count) + '건', 'red' if error_count else 'green')}  "
        f"경고 {style(str(warn_count) + '건', 'yellow' if warn_count else 'green')}",
    ]
    return "\n".join(lines)


def render_nginx_summary(result: dict) -> str:
    if result["status"] != "ok":
        return render_logs(result)

    summary = result.get("summary") or {}
    header = f"Log: {result['path']} {badge('ok', 'green')}"

    total = summary.get("total", 0)
    if total == 0:
        return "\n".join([header, "", "파싱된 라인이 없습니다. (nginx Combined Log Format 확인 필요)"])

    lines = [
        header,
        "",
        f"{style('Nginx Access Log 요약', 'bold')} — 총 {total:,}건",
        "",
        style("상태 코드:", "cyan"),
    ]

    status_dist: dict = summary.get("status_dist", {})
    for code in sorted(status_dist):
        count = status_dist[code]
        pct = count / total * 100
        color = "green" if code < 400 else "yellow" if code < 500 else "red"
        lines.append(f"  {style(str(code), color)}   {count:>6,}  ({pct:.1f}%)")

    top_paths: list = summary.get("top_paths", [])
    if top_paths:
        lines += ["", style("상위 경로 (Top 10):", "cyan")]
        for path, count in top_paths:
            lines.append(f"  {path:<40} {count:>6,}")

    top_ips: list = summary.get("top_ips", [])
    if top_ips:
        lines += ["", style("상위 IP (Top 10):", "cyan")]
        for ip, count in top_ips:
            lines.append(f"  {ip:<30} {count:>6,}")

    error_count = len(summary.get("error_lines", []))
    lines += ["", f"4xx/5xx 에러: {style(str(error_count) + '건', 'red' if error_count else 'green')}"]

    return "\n".join(lines)


def render_docker_containers(containers: list) -> str:
    if not containers:
        return "실행 중인 컨테이너가 없습니다. Docker가 설치되어 있는지 확인하세요."

    rows = [
        style(f"  {'NAME':<22} {'STATUS':<22} IMAGE", "bold"),
    ]
    for c in containers:
        rows.append(f"  {c['name']:<22} {c['status']:<22} {c['image']}")

    hints = ["", style("등록 명령어:", "cyan")]
    for c in containers:
        name = c["name"]
        hints.append(f"  /log add @{name:<16} -docker {name}")

    return "\n".join(["실행 중인 Docker 컨테이너", "", *rows, *hints])


def render_service(result: dict) -> str:
    status_color = "green" if result["status"] == "ok" else "yellow" if result["status"] == "unknown" else "red"
    return f"Service: {result['name']} {badge(result['status'], status_color)}\n{result['details']}"


def _process_lines(processes: list[dict]) -> list[str]:
    if not processes:
        return ["no process data"]
    return [
        f"{proc['pid']:<8} {proc['cpu']:>5.1f}  {proc['mem']:>5.1f}  {proc['command']}"
        for proc in processes
    ]


def _memory(memory: dict) -> str:
    return f"{_percent(memory.get('percent'))} used, {human_bytes(memory.get('available'))} available"


def _percent(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f}%"


def _load(value: tuple[float, float, float] | None) -> str:
    if not value:
        return "unknown"
    return ", ".join(f"{item:.2f}" for item in value)


def clear_screen() -> str:
    if os.getenv("TERM") == "dumb":
        return ""
    return "\033[2J\033[H"


def prompt() -> str:
    return f"\n{style('monix', 'cyan')} {style('>', 'bold')} " if supports_color() else "\nmonix > "


def colorize_line(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith(("Alerts:", "주의:", "오류:")):
        return style(line, "red")
    if stripped.startswith(("CPU", "Memory", "메모리", "Disk", "디스크", "Load")):
        return style(line, "cyan")
    if stripped.startswith(("-", "  -")):
        return style(line, "muted")
    return line


def badge(value: str, color: str) -> str:
    return style(f"[{value}]", color)


def style(value: str, color: str) -> str:
    if not supports_color():
        return value
    codes = {
        "bold": "1",
        "muted": "2",
        "red": "31",
        "green": "32",
        "yellow": "33",
        "cyan": "36",
        "magenta": "35",
    }
    code = codes.get(color)
    if not code:
        return value
    return f"\033[{code}m{value}\033[0m"


def supports_color() -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("TERM") == "dumb":
        return False
    return sys.stdout.isatty() or bool(os.getenv("CLICOLOR_FORCE"))


def _rule(width: int, position: str = "mid") -> str:
    del position
    return style("+" + "-" * (width - 2) + "+", "muted")


def _line(label: str, value: str, inner: int) -> str:
    left = f"{style(f'{label:<12}', 'cyan')} {value}"
    return _text(left, inner)


def _text(value: str, inner: int) -> str:
    clipped = _clip_ansi(value, inner)
    padding = inner - _visible_len(clipped)
    return f"{style('|', 'muted')} {clipped}{' ' * padding} {style('|', 'muted')}"


def _metric(label: str, value: float | None, inner: int, suffix: str = "") -> str:
    percent = _percent(value)
    bar = _bar(value)
    suffix_text = f"  {style(suffix, 'muted')}" if suffix else ""
    return _text(f"{style(f'{label:<12}', 'cyan')} {bar} {percent:>8}{suffix_text}", inner)


def _bar(value: float | None, width: int = 24) -> str:
    if value is None:
        return "[" + "?" * width + "]"
    filled = max(0, min(width, round((value / 100) * width)))
    color = "green" if value < 70 else "yellow" if value < 85 else "red"
    return "[" + style("#" * filled, color) + style("-" * (width - filled), "muted") + "]"


def _visible_len(value: str) -> int:
    length = 0
    in_escape = False
    for char in value:
        if char == "\033":
            in_escape = True
            continue
        if in_escape:
            if char == "m":
                in_escape = False
            continue
        length += 1
    return length


def _clip_ansi(value: str, max_len: int) -> str:
    result = []
    visible = 0
    in_escape = False
    for char in value:
        if char == "\033":
            in_escape = True
            result.append(char)
            continue
        if in_escape:
            result.append(char)
            if char == "m":
                in_escape = False
            continue
        if visible >= max_len:
            break
        result.append(char)
        visible += 1
    if supports_color() and result and not "".join(result).endswith("\033[0m"):
        result.append("\033[0m")
    return "".join(result)
