from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata

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

_BANNER = [
    "▓▓▓    ▓▓▓  ▓▓▓▓▓▓  ▓▓▓   ▓▓  ▓▓  ▓▓   ▓▓",
    "▓▓▓▓  ▓▓▓▓ ▓▓    ▓▓ ▓▓▓▓  ▓▓  ▓▓   ▓▓ ▓▓ ",
    "▓▓ ▓▓▓▓ ▓▓ ▓▓    ▓▓ ▓▓ ▓▓ ▓▓  ▓▓    ▓▓▓  ",
    "▓▓  ▓▓  ▓▓ ▓▓    ▓▓ ▓▓  ▓▓▓▓  ▓▓   ▓▓ ▓▓ ",
    "▓▓      ▓▓  ▓▓▓▓▓▓  ▓▓   ▓▓▓  ▓▓  ▓▓   ▓▓",
]
# 256-color cyan gradient: dark teal → bright aqua (top → bottom)
_BANNER_GRAD = [23, 30, 37, 44, 51]

_MASCOT = [
    r"         ███        ",
    r"       ███████      ",
    r"      █████████     ",
    r"       █     █      ",
    r"       █     █      ",
    r"      █████████     ",
    r"     ███████████    ",
    r"    ███  ███  ███   ",
    r"    █████████████   ",
    r"     ███████████    ",
]


def render_welcome(snapshot: dict, gemini_enabled: bool) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    mode = badge("Gemini AI", "green") if gemini_enabled else badge("Local monitor", "yellow")
    alerts = snapshot.get("alerts") or []
    alert_text = badge(f"{len(alerts)} alert(s)", "red") if alerts else badge("healthy", "green")
    disk = (snapshot.get("disks") or [{}])[0]
    memory = snapshot.get("memory", {})

    # Banner: borderless centered MONIX ASCII art with 256-color gradient
    def _banner_row(line: str, color_code: int) -> str:
        pad = max(0, (width - len(line)) // 2)
        if supports_color():
            return f"\033[38;5;{color_code}m{' ' * pad}{line}\033[0m"
        return " " * pad + line

    banner_section = (
        [""]
        + [_banner_row(line, _BANNER_GRAD[i]) for i, line in enumerate(_BANNER)]
        + [""]
    )

    # Side-by-side: mascot (left) + right column (metrics ─── info)
    mascot_w = max(len(line) for line in _MASCOT)
    sep = 2
    right_inner = inner - mascot_w - sep
    bar_w = 16 if right_inner >= 50 else max(8, right_inner - 28)

    def _rm(label: str, value: float | None, suffix: str = "") -> str:
        bar = _bar(value, width=bar_w)
        suf = f"  {style(suffix, 'muted')}" if suffix and right_inner >= 50 else ""
        return f"{style(f'{label:<9}', 'cyan')} {bar} {_percent(value):>7}{suf}"

    def _rl(label: str, value: str) -> str:
        return f"{style(f'{label:<9}', 'cyan')} {value}"

    metric_rows: list[str] = [
        _rm("CPU", snapshot.get("cpu_percent")),
        _rm("Memory", memory.get("percent"), f"{human_bytes(memory.get('available'))} free"),
        _rm("Disk /", disk.get("percent"), f"{human_bytes(disk.get('free'))} free"),
        _rl("Load", _load(snapshot.get("load_average"))),
        _rl("Status", alert_text),
    ]
    info_rows: list[str] = [
        f"{style('Monix', 'bold')} {style('server monitor', 'muted')}  v{__version__}  {mode}",
        f"{style('Host', 'cyan')} {snapshot.get('host', 'unknown')}  {style(snapshot.get('os', ''), 'muted')}",
    ]
    divider = style("─" * right_inner, "muted")
    content_rows = metric_rows + [divider] + info_rows

    n_mascot = len(_MASCOT)
    n_content = len(content_rows)
    pad_top = (n_mascot - n_content) // 2
    pad_bottom = n_mascot - n_content - pad_top
    right_rows = [""] * pad_top + content_rows + [""] * pad_bottom

    def _combined(mascot_line: str, right_content: str) -> str:
        left_raw = style(mascot_line, "cyan")
        left_pad = " " * (mascot_w - len(mascot_line))
        right_clipped = _clip_ansi(right_content, right_inner)
        right_pad = " " * (right_inner - _visible_len(right_clipped))
        return (
            f"{style('│', 'muted')} "
            f"{left_raw}{left_pad}{' ' * sep}"
            f"{right_clipped}{right_pad} "
            f"{style('│', 'muted')}"
        )

    combined = [_combined(m, right_rows[i]) for i, m in enumerate(_MASCOT)]

    lines = [
        *banner_section,
        _rule(width, "top"),
        *combined,
        _rule(width, "mid"),
        _text(f"{style('Ask me anything!', 'bold')}  Check CPU    Why is nginx slow?    Memory analysis", inner),
        _text(f"{style('/help', 'cyan')} Commands   {style('/clear', 'cyan')} Clear history   {style('/watch cpu', 'cyan')} Real-time   {style('/exit', 'cyan')} Exit", inner),
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


def render_top(procs: list[dict], disks: list[dict], count: int, metric: str = "all") -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    m = metric.lower()

    by_cpu  = sorted(procs, key=lambda r: r["cpu"], reverse=True)[:count]
    by_mem  = sorted(procs, key=lambda r: r["mem"], reverse=True)[:count]
    by_disk = sorted(disks, key=lambda d: d.get("percent") or 0, reverse=True)

    def _proc_header(label: str) -> list[str]:
        return [
            _rule(width),
            _text(style(label, "cyan"), inner),
            _text(
                f"{style('PID', 'muted'):<18} {style('USAGE', 'muted'):>7}  {style('COMMAND', 'muted')}",
                inner,
            ),
        ]

    def _proc_rows(rows: list[dict], key: str) -> list[str]:
        result = []
        for p in rows:
            val = p[key]
            color = "red" if val >= 50 else "yellow" if val >= 20 else "green"
            result.append(_text(
                f"{style(str(p['pid']), 'muted'):<18} {style(f'{val:>5.1f}%', color):>7}  {style(p['command'], 'cyan')}",
                inner,
            ))
        if not rows:
            result.append(_text(style("no data", "muted"), inner))
        return result

    def _disk_rows() -> list[str]:
        result = [
            _rule(width),
            _text(style("Disk", "cyan"), inner),
            _text(
                f"{style('MOUNT', 'muted'):<22} {style('USED%', 'muted'):>7}  {style('FREE / TOTAL', 'muted')}",
                inner,
            ),
        ]
        for d in by_disk:
            pct = d.get("percent") or 0
            color = "red" if pct >= 90 else "yellow" if pct >= 75 else "green"
            free_total = f"{human_bytes(d.get('free'))} / {human_bytes(d.get('total'))}"
            result.append(_text(
                f"{d.get('path', '?'):<22} {style(f'{pct:>5.1f}%', color):>7}  {free_total}",
                inner,
            ))
        if not by_disk:
            result.append(_text(style("no disk data", "muted"), inner))
        return result

    lines = [
        _rule(width, "top"),
        _text(f"{style('Top', 'bold')}  {style(metric, 'cyan')}  {style(f'top {count}', 'muted')}", inner),
    ]

    if m in ("cpu", "all"):
        lines += [*_proc_header("CPU %"), *_proc_rows(by_cpu, "cpu")]
    if m in ("memory", "mem", "all"):
        lines += [*_proc_header("Memory %"), *_proc_rows(by_mem, "mem")]
    if m in ("disk", "all"):
        lines += _disk_rows()

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


def render_docker_stats(stats: list[dict]) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 130)
    inner = max(width - 4, 60)
    lines = [_rule(width, "top"), _text(style("Docker Stats", "bold"), inner), _rule(width, "mid")]

    if not stats:
        lines += [_text("No containers running.", inner), _rule(width, "bottom")]
        return "\n".join(lines)

    first = stats[0]
    if "error" in first:
        lines += [_text(first["error"], inner), _rule(width, "bottom")]
        return "\n".join(lines)

    lines.append(_text(
        f"  {style('NAME', 'bold'):<30}  {'CPU%':>7}  {'MEM%':>6}  {'MEM USAGE':<18}  {'NET I/O':<22}  {'BLOCK I/O':<18}  {'PIDs':>4}",
        inner,
    ))
    lines.append(_rule(width))
    for s in stats:
        name = (s.get("Name") or "?")[:28]
        cpu = s.get("CPUPerc") or "-"
        mem_pct = s.get("MemPerc") or "-"
        mem_usage = s.get("MemUsage") or "-"
        net_io = s.get("NetIO") or "-"
        block_io = s.get("BlockIO") or "-"
        pids = s.get("PIDs") or "-"
        lines.append(_text(
            f"  {name:<30}  {cpu:>7}  {mem_pct:>6}  {mem_usage:<18}  {net_io:<22}  {block_io:<18}  {pids:>4}",
            inner,
        ))
    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_docker_top(result: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    container = result.get("container", "?")
    lines = [
        _rule(width, "top"),
        _text(f"{style('Docker Top', 'bold')}  {style(container, 'cyan')}", inner),
        _rule(width, "mid"),
    ]
    if result.get("status") != "ok":
        lines += [_text(result.get("error", "unknown error"), inner), _rule(width, "bottom")]
        return "\n".join(lines)

    headers = result.get("headers") or []
    rows = result.get("rows") or []
    if not rows:
        lines += [_text("No processes.", inner), _rule(width, "bottom")]
        return "\n".join(lines)

    if headers:
        header_str = "  " + "  ".join(
            f"{h:<12}" if i < len(headers) - 1 else h for i, h in enumerate(headers)
        )
        lines.append(_text(style(header_str, "bold"), inner))
        lines.append(_rule(width))

    for row in rows:
        row_str = "  " + "  ".join(
            f"{cell:<12}" if i < len(row) - 1 else cell for i, cell in enumerate(row)
        )
        lines.append(_text(row_str, inner))

    lines.append(_rule(width, "bottom"))
    return "\n".join(lines)


def render_docker_inspect(info: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    container = info.get("container", "?")
    lines = [
        _rule(width, "top"),
        _text(f"{style('Docker Inspect', 'bold')}  {style(container, 'cyan')}", inner),
        _rule(width, "mid"),
    ]
    if info.get("status") != "ok":
        lines += [_text(info.get("error", "unknown error"), inner), _rule(width, "bottom")]
        return "\n".join(lines)

    state = info.get("state", "?")
    state_color = "green" if state == "running" else "red"
    health = info.get("health_status", "none")
    health_color = "green" if health == "healthy" else "yellow" if health in ("none", "starting") else "red"

    started = (info.get("started_at") or "?")[:19].replace("T", " ")
    lines += [
        _line("Name", info.get("name", "?"), inner),
        _line("Image", info.get("image", "?"), inner),
        _line("State", style(state, state_color), inner),
        _line("Health", style(health, health_color), inner),
        _line("Started", started, inner),
        _line("Restarts", str(info.get("restart_count", 0)), inner),
    ]

    networks = info.get("networks") or []
    ip = info.get("ip_address") or ""
    net_str = ", ".join(networks) + (f"  ({ip})" if ip else "")
    if net_str:
        lines.append(_line("Networks", net_str, inner))

    ports = info.get("ports") or []
    if ports:
        lines.append(_rule(width))
        lines.append(_text(style("Ports", "cyan"), inner))
        for p in ports:
            lines.append(_text(f"  {p}", inner))

    mounts = info.get("mounts") or []
    if mounts:
        lines.append(_rule(width))
        lines.append(_text(style("Mounts", "cyan"), inner))
        for m in mounts:
            mode = f" [{m['mode']}]" if m.get("mode") else ""
            lines.append(_text(f"  {m.get('source', '?')} → {m.get('destination', '?')}{mode}", inner))

    env = info.get("env") or []
    if env:
        lines.append(_rule(width))
        lines.append(_text(style("Environment", "cyan"), inner))
        for e in env[:10]:
            lines.append(_text(f"  {e}", inner))
        if len(env) > 10:
            lines.append(_text(style(f"  … and {len(env) - 10} more", "muted"), inner))

    lines.append(_rule(width, "bottom"))
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


def render_service_list(result: dict) -> str:
    width = min(shutil.get_terminal_size((100, 24)).columns, 110)
    inner = max(width - 4, 60)
    services = result.get("services", [])
    lines = [
        _rule(width, "top"),
        _text(f"{style('Services', 'bold')}  {badge(str(len(services)), 'cyan')}", inner),
        _rule(width, "mid"),
    ]
    if result["status"] == "unknown":
        lines.append(_text(style(result.get("details", ""), "muted"), inner))
    elif not services:
        lines.append(_text(style("no running services found", "muted"), inner))
    else:
        col_name = 36
        col_sub = 10
        header = (
            f"{style('UNIT', 'muted'):<{col_name + 9}}"
            f"{style('STATE', 'muted'):<{col_sub + 9}}"
            f"{style('DESCRIPTION', 'muted')}"
        )
        lines.append(_text(header, inner))
        for svc in services:
            active = svc["active"]
            sub = svc["sub"]
            color = "green" if sub == "running" else "red" if active in ("failed", "inactive") else "yellow"
            name_col = _clip_ansi(style(svc["name"], "cyan"), col_name)
            name_pad = " " * max(0, col_name - _visible_len(name_col))
            sub_col = style(sub, color)
            sub_pad = " " * max(0, col_sub - len(sub))
            desc = svc["description"]
            row = f"{name_col}{name_pad}  {sub_col}{sub_pad}  {style(desc, 'muted')}"
            lines.append(_text(row, inner))
    lines.append(_rule(width, "bottom"))
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
        eaw = unicodedata.east_asian_width(char)
        length += 2 if eaw in ("W", "F") else 1
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
        eaw = unicodedata.east_asian_width(char)
        char_width = 2 if eaw in ("W", "F") else 1
        if visible + char_width > max_len:
            break
        result.append(char)
        visible += char_width
    if supports_color() and result and not "".join(result).endswith("\033[0m"):
        result.append("\033[0m")
    return "".join(result)
