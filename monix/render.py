from __future__ import annotations

import os
import re
import shutil
import sys

from monix import __version__
from monix.tools.system import human_bytes

_LOG_ERROR_RE = re.compile(r"\b(ERROR|FATAL|CRITICAL|Exception|Traceback)\b", re.IGNORECASE)
_LOG_WARN_RE  = re.compile(r"\b(WARN(?:ING)?)\b", re.IGNORECASE)

# syslog: "Apr 26 14:38:29 hostname process[pid]: message"
_SYSLOG_RE = re.compile(
    r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(\S+?)(\[\d+\])?:\s*(.*)"
)
# ISO timestamp: "2024-01-15 10:23:45[.fff][Z/±HH:MM] ..."
_ISO_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+(.*)"
)
# [INFO] / [DEBUG] / [TRACE] / [NOTICE] bracket level tags
_BRACKET_INFO_RE = re.compile(r"\[(?:INFO|NOTICE|DEBUG|TRACE)\]", re.IGNORECASE)

_MASCOT = [
    r"        ███        ",
    r"      ███████      ",
    r"     █████████     ",
    r"      █     █     ",
    r"      █     █     ",
    r"    ███████████    ",
    r"   █████████████   ",
    r"  ███████████████  ",
    r"  ████  ███  ████  ",
    r"   █████████████  ",
    r"    ███████████   ",
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
        _text(f"{style('Ask me anything!', 'bold')}  Check CPU    Why is nginx slow?    Memory analysis", inner),
        _text(f"{style('/help', 'cyan')} Commands   {style('/clear', 'cyan')} Clear history   {style('/watch 5', 'cyan')} Real-time   {style('/exit', 'cyan')} Exit", inner),
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


def render_cpu(cpu_percent: float | None, load: tuple | None) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    return "\n".join([
        _rule(width, "top"),
        _text(style("CPU", "bold"), inner),
        _rule(width, "mid"),
        _metric("CPU", cpu_percent, inner),
        _line("Load avg", _load(load), inner),
        _rule(width, "bottom"),
    ])


def render_memory(memory: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    return "\n".join([
        _rule(width, "top"),
        _text(style("Memory", "bold"), inner),
        _rule(width, "mid"),
        _metric("Memory", memory.get("percent"), inner, suffix=f"{human_bytes(memory.get('available'))} free"),
        _line("Used", human_bytes(memory.get("used")), inner),
        _line("Available", human_bytes(memory.get("available")), inner),
        _line("Total", human_bytes(memory.get("total")), inner),
        _rule(width, "bottom"),
    ])


def render_disk(disks: list[dict]) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    lines = [_rule(width, "top"), _text(style("Disk", "bold"), inner), _rule(width, "mid")]
    for disk in disks:
        suffix = f"{human_bytes(disk.get('free'))} free / {human_bytes(disk.get('total'))}"
        lines.append(_metric(disk["path"], disk.get("percent"), inner, suffix=suffix))
    if not disks:
        lines.append(_text("no disk data", inner))
    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_network(interfaces: list[dict]) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    lines = [_rule(width, "top"), _text(style("Network I/O", "bold"), inner), _rule(width, "mid")]
    visible = [i for i in interfaces if i["rx_bps"] > 0 or i["tx_bps"] > 0 or
               i.get("rx_bytes_total", 0) + i.get("tx_bytes_total", 0) >= 100 * 1024 * 1024]
    if not visible:
        visible = interfaces[:3]  # fallback: show top 3 even if idle
    if not visible:
        lines.append(_text("no network data", inner))
    else:
        for iface in visible:
            rx = human_bytes(int(iface["rx_bps"])) + "/s"
            tx = human_bytes(int(iface["tx_bps"])) + "/s"
            label = iface["interface"]
            lines.append(_line(f"{label:<12}", f"↓ {rx:<14}  ↑ {tx}", inner))
    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_swap(swap: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    total = swap.get("total") or 0
    if total == 0:
        return "\n".join([
            _rule(width, "top"),
            _text(style("Swap", "bold"), inner),
            _rule(width),
            _text("No swap (disabled)", inner),
            _rule(width),
        ])
    return "\n".join([
        _rule(width, "top"),
        _text(style("Swap", "bold"), inner),
        _rule(width, "mid"),
        _metric("Swap", swap.get("percent"), inner, suffix=f"{human_bytes(swap.get('free'))} free"),
        _line("Used", human_bytes(swap.get("used")), inner),
        _line("Free", human_bytes(swap.get("free")), inner),
        _line("Total", human_bytes(swap.get("total")), inner),
        _rule(width, "bottom"),
    ])


def render_disk_io(devices: list[dict]) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    lines = [_rule(width, "top"), _text(style("Disk I/O", "bold"), inner), _rule(width, "mid")]
    if not devices:
        lines.append(_text("no disk I/O data", inner))
    else:
        for dev in devices:
            read_s = human_bytes(int(dev["read_bps"])) + "/s"
            write_s = human_bytes(int(dev["write_bps"])) + "/s"
            label = dev["device"]
            lines.append(_line(f"{label:<12}", f"R {read_s:<14}  W {write_s}", inner))
    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_stat(snapshot: dict, swap: dict, interfaces: list[dict], devices: list[dict]) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    memory = snapshot.get("memory", {})
    disk = (snapshot.get("disks") or [{}])[0]
    alerts = snapshot.get("alerts") or []
    alert_text = badge(f"{len(alerts)} alert(s)", "red") if alerts else badge("healthy", "green")
    swap_total = swap.get("total") or 0

    lines = [
        _rule(width, "top"),
        _text(f"{style('Stat', 'bold')}  {snapshot.get('host', '')}  {style(snapshot.get('time', ''), 'muted')}  {alert_text}", inner),
        _rule(width, "mid"),
        _metric("CPU", snapshot.get("cpu_percent"), inner),
        _line("Load", _load(snapshot.get("load_average")), inner),
        _metric("Memory", memory.get("percent"), inner, suffix=f"{human_bytes(memory.get('available'))} free"),
        (_metric("Swap", swap.get("percent"), inner, suffix=f"{human_bytes(swap.get('free'))} free")
         if swap_total > 0 else _text(style("Swap        disabled", "muted"), inner)),
        _metric(disk.get("path", "/"), disk.get("percent"), inner, suffix=f"{human_bytes(disk.get('free'))} free"),
        _rule(width, "mid"),
        _text(style("Network I/O", "cyan"), inner),
        *_net_stat_lines(interfaces, inner),
        _rule(width, "mid"),
        _text(style("Disk I/O", "cyan"), inner),
        *_io_stat_lines(devices, inner),
        _rule(width, "mid"),
        _text(style("Top Processes", "cyan"), inner),
        *[_text(line, inner) for line in _process_lines(snapshot.get("top_processes", []))],
        _rule(width, "bottom"),
    ]
    return "\n".join(lines)


def _net_stat_lines(interfaces: list[dict], inner: int) -> list[str]:
    visible = [i for i in interfaces
               if i["rx_bps"] > 0 or i["tx_bps"] > 0
               or i.get("rx_bytes_total", 0) + i.get("tx_bytes_total", 0) >= 100 * 1024 * 1024]
    if not visible:
        visible = interfaces[:2]
    if not visible:
        return [_text("no data", inner)]
    return [
        _line(f"{i['interface']:<12}",
              f"↓ {human_bytes(int(i['rx_bps'])) + '/s':<14}  ↑ {human_bytes(int(i['tx_bps'])) + '/s'}",
              inner)
        for i in visible
    ]


def _io_stat_lines(devices: list[dict], inner: int) -> list[str]:
    if not devices:
        return [_text("no data", inner)]
    return [
        _line(f"{d['device']:<12}",
              f"R {human_bytes(int(d['read_bps'])) + '/s':<14}  W {human_bytes(int(d['write_bps'])) + '/s'}",
              inner)
        for d in devices[:3]
    ]


def render_history(records: list[dict], metric: str | None, period_label: str = "") -> str:
    """수집 이력을 테이블로 렌더링."""
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    m = (metric or "").lower()
    metric_label = {"cpu": "CPU", "memory": "메모리", "mem": "메모리", "disk": "디스크", "swap": "스왑", "net": "네트워크", "network": "네트워크", "io": "디스크 I/O"}.get(m, "전체")
    count_label = f"{len(records)}건"
    title_parts = [f"  {style(metric_label + ' 이력', 'bold')}"]
    if period_label:
        title_parts.append(f"  {style(period_label, 'muted')}")
    title_parts.append(f"  {style(count_label, 'muted')}")
    title = "  ·  ".join(p.strip() for p in title_parts)

    lines = [_rule(width, "top"), _text(title, inner), _rule(width)]

    if not records:
        lines += [_text("데이터가 없습니다.", inner), _rule(width, "bottom")]
        return "\n".join(lines)

    def _ts(r: dict) -> str:
        ts = r.get("_ts")
        if hasattr(ts, "strftime"):
            return ts.strftime("%m-%d %H:%M")
        return str(r.get("timestamp", ""))[:16]

    if m == "cpu":
        lines.append(_text(f"  {'시간':<16}  {'CPU':>7}   Load avg", inner))
        lines.append(_rule(width))
        for r in records:
            cpu = f"{r.get('cpu_percent') or 0:.1f}%"
            load = r.get("load_average") or []
            load_str = "  ".join(f"{v:.2f}" for v in load) if load else "-"
            lines.append(_text(f"  {_ts(r):<16}  {cpu:>7}   {load_str}", inner))

    elif m in ("memory", "mem"):
        lines.append(_text(f"  {'시간':<16}  {'메모리':>7}   Used", inner))
        lines.append(_rule(width))
        for r in records:
            mem = r.get("memory") or {}
            pct = f"{mem.get('percent') or 0:.1f}%"
            used = human_bytes(mem.get("used"))
            lines.append(_text(f"  {_ts(r):<16}  {pct:>7}   {used}", inner))

    elif m == "disk":
        lines.append(_text(f"  {'시간':<16}  {'디스크':>7}   Mount", inner))
        lines.append(_rule(width))
        for r in records:
            disks = r.get("disks") or []
            if disks:
                first = disks[0]
                pct = f"{first.get('percent') or 0:.1f}%"
                lines.append(_text(f"  {_ts(r):<16}  {pct:>7}   {first.get('path', '/')}", inner))

    elif m == "swap":
        lines.append(_text(f"  {'시간':<16}  {'스왑':>7}   Used", inner))
        lines.append(_rule(width))
        for r in records:
            swap = r.get("swap") or {}
            pct = f"{swap.get('percent') or 0:.1f}%" if swap.get("percent") is not None else "-"
            used = human_bytes(swap.get("used"))
            lines.append(_text(f"  {_ts(r):<16}  {pct:>7}   {used}", inner))

    else:  # all / net / io → 전체 요약
        lines.append(_text(f"  {'시간':<16}  {'CPU':>7}  {'메모리':>7}  {'디스크':>7}", inner))
        lines.append(_rule(width))
        for r in records:
            cpu = f"{r.get('cpu_percent') or 0:.1f}%"
            mem = r.get("memory") or {}
            mem_pct = f"{mem.get('percent') or 0:.1f}%"
            disks = r.get("disks") or []
            disk_pct = f"{disks[0].get('percent') or 0:.1f}%" if disks else "-"
            lines.append(_text(f"  {_ts(r):<16}  {cpu:>7}  {mem_pct:>7}  {disk_pct:>7}", inner))

    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_processes(processes: list[dict]) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    lines = [
        _rule(width, "top"),
        _text(style("Top Processes", "bold"), inner),
        _rule(width, "mid"),
        _text(
            f"{style('PID', 'muted'):<18} {style('CPU%', 'muted'):>9} {style('MEM%', 'muted'):>9}  {style('COMMAND', 'muted')}",
            inner,
        ),
    ]
    for proc in (processes or []):
        cpu_color = "bold_red" if proc["cpu"] >= 50 else "yellow" if proc["cpu"] >= 20 else "green"
        mem_color = "bold_red" if proc["mem"] >= 30 else "yellow" if proc["mem"] >= 10 else "green"
        pid_str  = style(f"{proc['pid']:<8}", "muted")
        cpu_str  = style(f"{proc['cpu']:>5.1f}", cpu_color)
        mem_str  = style(f"{proc['mem']:>5.1f}", mem_color)
        cmd_str  = style(proc["command"], "cyan")
        lines.append(_text(f"{pid_str}  {cpu_str}  {mem_str}  {cmd_str}", inner))
    if not processes:
        lines.append(_text(style("no process data", "muted"), inner))
    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_logs(result: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    path   = result.get("path") or "unknown"
    status = result["status"]
    sc     = "green" if status == "ok" else "red"
    title  = f"{style(path, 'bold_cyan')}  {badge(status, sc)}"
    lines  = [_rule(width, "top"), _text(title, inner), _rule(width, "mid")]
    if status != "ok":
        lines.append(_text(style(f"읽기 실패: {status}", "red"), inner))
    else:
        log_lines = result.get("lines") or []
        if not log_lines:
            lines.append(_text(style("(빈 파일)", "muted"), inner))
        for ln in log_lines:
            lines.append(_text(colorize_log_line(ln), inner))
    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_log_list(entries: list) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    _TC = {"app": "green", "nginx": "yellow", "docker": "cyan"}
    if not entries:
        return "\n".join([
            _rule(width, "top"),
            _text(style("Logs", "bold"), inner),
            _rule(width, "mid"),
            _text(style("등록된 로그가 없습니다.", "muted"), inner),
            _text(style("/log add @alias -app /path/to/file 로 등록하세요.", "muted"), inner),
            _rule(width, "bottom"),
        ])
    rows = [
        _rule(width, "top"),
        _text(f"{style('Logs', 'bold')}  {badge(str(len(entries)) + '개', 'cyan')}", inner),
        _rule(width, "mid"),
    ]
    for e in entries:
        target = e.path or e.container or "(없음)"
        tc = _TC.get(e.type, "muted")
        rows.append(_text(
            f"{style(f'@{e.alias:<20}', 'cyan')} {badge(f'{e.type:<6}', tc)}  {style(target, 'muted')}",
            inner,
        ))
    rows.append(_rule(width, "bottom"))
    return "\n".join(rows)


def render_log_aliases(alias_list: list[str]) -> str:
    if not alias_list:
        return "등록된 로그가 없습니다. /log add 로 등록하세요."
    return "\n".join([
        style("등록된 로그 aliases:", "bold"),
        *(f"  {style('@' + a, 'cyan')}" for a in alias_list),
    ])


def colorize_log_line(line: str) -> str:
    # ── ERROR/FATAL: 줄 전체 red + 키워드 bold ───────────────────────
    if _LOG_ERROR_RE.search(line):
        hl = _LOG_ERROR_RE.sub(lambda m: f"\033[1m{m.group()}\033[0;31m", line)
        return f"\033[31m{hl}\033[0m"
    # ── WARN: 줄 전체 yellow + 키워드 bold ──────────────────────────
    if _LOG_WARN_RE.search(line):
        hl = _LOG_WARN_RE.sub(lambda m: f"\033[1m{m.group()}\033[0;33m", line)
        return f"\033[33m{hl}\033[0m"
    # ── syslog: "Apr 26 14:38:29 hostname process[pid]: message" ────
    m = _SYSLOG_RE.match(line)
    if m:
        ts, host, proc, pid, msg = m.groups()
        msg = _BRACKET_INFO_RE.sub(lambda x: style(x.group(), "cyan"), msg)
        return (
            style(ts, "muted") + " "
            + style(host, "muted") + " "
            + style(proc, "cyan")
            + style(pid or "", "muted") + ": "
            + msg
        )
    # ── ISO timestamp: "2024-01-15 10:23:45 …" ──────────────────────
    m = _ISO_TS_RE.match(line)
    if m:
        ts, rest = m.groups()
        rest = _BRACKET_INFO_RE.sub(lambda x: style(x.group(), "cyan"), rest)
        return style(ts, "muted") + " " + rest
    return line


def render_log_search(result: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    path   = result["path"]
    status = result["status"]

    if status != "ok":
        return "\n".join([
            _rule(width, "top"),
            _text(f"{style(path, 'bold_cyan')}  {badge(status, 'red')}", inner),
            _rule(width, "bottom"),
        ])

    query        = result.get("query")
    total        = result.get("total_scanned", 0)
    matches: list[dict] = result.get("matches", [])

    query_label  = f'"{query}"' if query else "에러/경고"
    error_count  = sum(1 for m in matches if m["severity"] == "error")
    warn_count   = sum(1 for m in matches if m["severity"] == "warn")
    found_color  = "red" if error_count else "yellow" if warn_count else "green"
    found_text   = f"{len(matches)} found" if matches else "healthy"

    summary = (
        f"{style(query_label, 'bold_cyan')} — "
        f"{style(f'{total:,} lines scanned', 'muted')}  "
        f"{badge(found_text, found_color)}"
    )
    lines = [
        _rule(width, "top"),
        _text(style(path, "bold_cyan"), inner),
        _text(summary, inner),
        _rule(width, "mid"),
    ]

    if not matches:
        lines.append(_text(style("이상 없음", "green"), inner))
    else:
        for m in matches:
            sev_color = "bold_red" if m["severity"] == "error" else "bold_yellow"
            lineno = style(f"L{m['lineno']:>6}", "muted")
            sev    = style(f"{'ERR' if m['severity'] == 'error' else 'WRN':>3}", sev_color)
            lines.append(_text(f"{lineno}  {sev}  {colorize_log_line(m['line'])}", inner))
        lines += [
            _rule(width, "mid"),
            _text(
                f"  {style('ERROR', 'bold_red')} {style(str(error_count), 'red')}   "
                f"{style('WARN', 'bold_yellow')} {style(str(warn_count), 'yellow')}",
                inner,
            ),
        ]

    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_nginx_summary(result: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)

    if result["status"] != "ok":
        return render_logs(result)

    summary = result.get("summary") or {}
    path  = result["path"]
    total = summary.get("total", 0)

    if total == 0:
        return "\n".join([
            _rule(width, "top"),
            _text(f"{style(path, 'bold_cyan')}  {badge('ok', 'green')}", inner),
            _rule(width, "mid"),
            _text(style("파싱된 라인 없음", "muted"), inner),
            _rule(width, "bottom"),
        ])

    lines = [
        _rule(width, "top"),
        _text(
            f"{style('Nginx Access Log', 'bold')}  {style(path, 'muted')}  {badge('ok', 'green')}",
            inner,
        ),
        _text(f"{style('Total', 'cyan')}  {style(f'{total:,} requests', 'muted')}", inner),
        _rule(width, "mid"),
        _text(style("Status Codes", "bold_cyan"), inner),
    ]

    status_dist: dict = summary.get("status_dist", {})
    for code in sorted(status_dist):
        count = status_dist[code]
        pct   = count / total * 100
        bw    = 16
        filled = max(0, min(bw, round(pct / 100 * bw)))
        color  = "green" if code < 400 else "yellow" if code < 500 else "red"
        bar    = style("█" * filled, color) + style("░" * (bw - filled), "muted")
        lines.append(_text(
            f"  {style(str(code), color)}  {bar}  {count:>6,}  {style(f'{pct:.1f}%', 'muted')}",
            inner,
        ))

    top_paths: list = summary.get("top_paths", [])
    if top_paths:
        lines += [_rule(width, "mid"), _text(style("Top Paths", "bold_cyan"), inner)]
        for p, count in top_paths:
            pct = count / total * 100
            lines.append(_text(
                f"  {style(f'{count:>6,}', 'cyan')}  {style(f'{pct:4.1f}%', 'muted')}  {p}",
                inner,
            ))

    top_ips: list = summary.get("top_ips", [])
    if top_ips:
        lines += [_rule(width, "mid"), _text(style("Top IPs", "bold_cyan"), inner)]
        for ip, count in top_ips:
            pct = count / total * 100
            lines.append(_text(
                f"  {style(f'{count:>6,}', 'cyan')}  {style(f'{pct:4.1f}%', 'muted')}  {ip}",
                inner,
            ))

    error_count = len(summary.get("error_lines", []))
    err_color   = "bold_red" if error_count else "green"
    lines += [
        _rule(width, "mid"),
        _text(f"  {style('4xx/5xx Errors', 'cyan')}  {style(str(error_count), err_color)}", inner),
        _rule(width, "bottom"),
    ]
    return "\n".join(lines)


def render_docker_containers(containers: list) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    if not containers:
        return "\n".join([
            _rule(width, "top"),
            _text(style("Docker Containers", "bold"), inner),
            _rule(width, "mid"),
            _text(style("실행 중인 컨테이너 없음", "muted"), inner),
            _rule(width, "bottom"),
        ])
    lines = [
        _rule(width, "top"),
        _text(
            f"{style('Docker Containers', 'bold')}  {badge(str(len(containers)) + '개 실행 중', 'green')}",
            inner,
        ),
        _rule(width, "mid"),
    ]
    for c in containers:
        sl = (c["status"] or "").lower()
        sc = "green" if ("up" in sl or "running" in sl) else "red" if ("exit" in sl or "dead" in sl or "stop" in sl) else "yellow"
        name_col   = style(f"{c['name']:<22}", "cyan")
        status_col = style(f"{c['status']:<22}", sc)
        image_col  = style(c["image"], "muted")
        lines.append(_text(f"{name_col} {status_col} {image_col}", inner))
    lines += [
        _rule(width, "mid"),
        _text(style("/docker add @alias <name>  로 alias 등록", "muted"), inner),
        _rule(width, "bottom"),
    ]
    return "\n".join(lines)


def render_docker_aliases(entries: list) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    docker_entries = [e for e in entries if e.type == "docker"]
    if not docker_entries:
        return "\n".join([
            _rule(width, "top"),
            _text(style("Docker Aliases", "bold"), inner),
            _rule(width, "mid"),
            _text(style("등록된 Docker 컨테이너가 없습니다.", "muted"), inner),
            _text(style("/docker add @alias <container>", "muted"), inner),
            _rule(width, "bottom"),
        ])
    lines = [
        _rule(width, "top"),
        _text(f"{style('Docker Aliases', 'bold')}  {badge(str(len(docker_entries)) + '개', 'cyan')}", inner),
        _rule(width, "mid"),
    ]
    for e in docker_entries:
        lines.append(_text(
            f"{style(f'@{e.alias:<20}', 'cyan')} {style(e.container or '(없음)', 'muted')}",
            inner,
        ))
    lines += [
        _rule(width, "mid"),
        _text(style("/docker @alias  |  --live  |  --search", "muted"), inner),
        _rule(width, "bottom"),
    ]
    return "\n".join(lines)


def render_service(result: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    sc = "green" if result["status"] == "ok" else "yellow" if result["status"] == "unknown" else "red"
    lines = [
        _rule(width, "top"),
        _text(f"{style(result['name'], 'bold_cyan')}  {badge(result['status'], sc)}", inner),
        _rule(width, "mid"),
    ]
    for ln in (result.get("details") or "").splitlines():
        stripped = ln.strip()
        if "active (running)" in stripped.lower():
            ln_col = style(ln, "green")
        elif any(w in stripped.lower() for w in ("inactive", "failed", "dead", "error")):
            ln_col = style(ln, "red")
        elif stripped.startswith("●") or stripped.startswith("*"):
            ln_col = style(ln, "bold_cyan")
        else:
            ln_col = style(ln, "muted") if stripped.startswith(("Loaded:", "Active:", "Docs:", "Process:", "Main PID:", "Tasks:", "Memory:", "CPU:", "CGroup:")) else ln
        lines.append(_text(ln_col, inner))
    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_tool_start(name: str) -> str:
    return f"  {style('⏺', 'cyan')}  {style(name, 'muted')}"


def render_tool_done(name: str, elapsed: float) -> str:
    return f"  {style('✔', 'green')}  {style(name, 'muted')}  {style(f'({elapsed:.1f}s)', 'muted')}"


def render_tool_fail(name: str, elapsed: float) -> str:
    return f"  {style('✖', 'red')}  {style(name, 'muted')}  {style(f'({elapsed:.1f}s)', 'muted')}"


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
    if stripped.startswith(("Alerts:", "Warning:", "Error:")):
        return style(line, "red")
    if stripped.startswith(("CPU", "Memory", "Disk", "Load")):
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
        "bold_red": "1;31",
        "bold_yellow": "1;33",
        "bold_green": "1;32",
        "bold_cyan": "1;36",
        "bold_magenta": "1;35",
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
    if position == "top":
        return style("┌" + "─" * (width - 2) + "┐", "muted")
    if position == "bottom":
        return style("└" + "─" * (width - 2) + "┘", "muted")
    return style("├" + "─" * (width - 2) + "┤", "muted")


def _line(label: str, value: str, inner: int) -> str:
    left = f"{style(f'{label:<12}', 'cyan')} {value}"
    return _text(left, inner)


def _text(value: str, inner: int) -> str:
    clipped = _clip_ansi(value, inner)
    padding = inner - _visible_len(clipped)
    return f"{style('│', 'muted')} {clipped}{' ' * padding} {style('│', 'muted')}"


def _metric(label: str, value: float | None, inner: int, suffix: str = "") -> str:
    percent = _percent(value)
    bar = _bar(value)
    suffix_text = f"  {style(suffix, 'muted')}" if suffix else ""
    return _text(f"{style(f'{label:<12}', 'cyan')} {bar} {percent:>8}{suffix_text}", inner)


def _bar(value: float | None, width: int = 24) -> str:
    if value is None:
        return style("░" * width, "muted")
    filled = max(0, min(width, round((value / 100) * width)))
    color = "green" if value < 70 else "yellow" if value < 85 else "red"
    return style("█" * filled, color) + style("░" * (width - filled), "muted")


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
