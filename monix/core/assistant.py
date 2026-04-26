from __future__ import annotations

import json
import textwrap

from monix.config import Settings
from monix.llm.gemini import GeminiClient
from monix.llm.types import LLMError
from monix.tools.calling import TOOL_DECLARATIONS, call_tool
from monix.tools.logs import registry
from monix.tools.system import collect_snapshot, human_bytes

_MAX_HISTORY = 20   # keep last 20 messages (~10 turns)
_MAX_TOOL_ROUNDS = 5  # max tool-call iterations per query to prevent infinite loops


def answer(question: str | list[str], settings: Settings | None = None, history: list[dict] | None = None) -> str:
    if isinstance(question, list):
        question = " ".join(question)
    settings = settings or Settings.from_env()
    snapshot = collect_snapshot(settings)
    client = GeminiClient(settings.gemini_api_key, settings.model)

    if client.enabled:
        snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2)
        log_entries = registry.load()
        registry_text = json.dumps(
            [{"alias": e.alias, "type": e.type, "path": e.path, "container": e.container} for e in log_entries],
            ensure_ascii=False,
        ) if log_entries else "[]"
        user_text = (
            f"{question}\n\n"
            f"[Current Server Snapshot]\n{snapshot_text}\n"
            f"Default log file: {settings.log_file}\n"
            f"[Registered Log Sources (alias → path/container)]\n{registry_text}"
        )
        user_msg = {"role": "user", "parts": [{"text": user_text}]}

        # working copy of history for this agentic loop — never mutate history directly
        working: list[dict] = list((history or [])[-_MAX_HISTORY:]) + [user_msg]

        try:
            for _ in range(_MAX_TOOL_ROUNDS):
                candidate, _usage = client.chat_with_tools(working, TOOL_DECLARATIONS)
                parts = candidate.get("parts") or []

                function_calls = [
                    p["functionCall"] for p in parts
                    if isinstance(p, dict) and "functionCall" in p
                ]
                text_parts = [
                    p["text"] for p in parts
                    if isinstance(p, dict) and isinstance(p.get("text"), str)
                ]
                text = "\n".join(text_parts).strip() or None

                if not function_calls:
                    _append_to_history(history, user_msg, text)
                    return wrap(text or local_answer(question, snapshot))

                # Append candidate verbatim — preserves thought_signature for thinking models
                working.append(candidate)

                responses = []
                for fc in function_calls:
                    fn_name = fc.get("name", "")
                    result = call_tool(fn_name, fc.get("args") or {})
                    responses.append(
                        {"functionResponse": {"name": fn_name, "response": {"result": result}}}
                    )
                working.append({"role": "user", "parts": responses})

            # _MAX_TOOL_ROUNDS exhausted — ask the LLM to summarise what it found
            candidate, _usage = client.chat_with_tools(working, [])
            parts = candidate.get("parts") or []
            text_parts = [
                p["text"] for p in parts
                if isinstance(p, dict) and isinstance(p.get("text"), str)
            ]
            text = "\n".join(text_parts).strip() or None
            _append_to_history(history, user_msg, text)
            return wrap(text or local_answer(question, snapshot))

        except LLMError as exc:
            return wrap(f"Gemini API 오류: {exc.message}\n\n{local_answer(question, snapshot)}")

    return wrap(local_answer(question, snapshot))


def _append_to_history(
    history: list[dict] | None,
    user_msg: dict,
    model_text: str | None,
) -> None:
    if history is None or not model_text:
        return
    history.append(user_msg)
    history.append({"role": "model", "parts": [{"text": model_text}]})
    if len(history) > _MAX_HISTORY:
        del history[: len(history) - _MAX_HISTORY]


def local_answer(question: str, snapshot: dict | None = None) -> str:
    snapshot = snapshot or collect_snapshot()
    lowered = question.lower()
    if any(word in lowered for word in ("cpu", "load", "load average")):
        return _cpu_answer(snapshot)
    if any(word in lowered for word in ("memory", "mem", "ram")):
        return _memory_answer(snapshot)
    if any(word in lowered for word in ("disk", "storage", "capacity")):
        return _disk_answer(snapshot)
    if any(word in lowered for word in ("process", "top", "processes")):
        return _process_answer(snapshot)
    return _summary_answer(snapshot)


def infer_service_name(tokens: list[str]) -> str | None:
    ignored = {"service", "status", "check", "show", "tell", "verify"}
    for token in tokens:
        cleaned = token.strip(".,:;()[]{}")
        if cleaned and cleaned.lower() not in ignored and not cleaned.startswith("/"):
            return cleaned
    return None


def wrap(text: str) -> str:
    paragraphs = []
    for paragraph in text.split("\n"):
        if not paragraph.strip() or paragraph.startswith(("-", " ", "\t", "*", "#")):
            paragraphs.append(paragraph)
        else:
            paragraphs.append(textwrap.fill(paragraph, width=100))
    return "\n".join(paragraphs)


def _summary_answer(snapshot: dict) -> str:
    alerts = snapshot.get("alerts") or []
    lines = [
        f"Status summary for {snapshot['host']}",
        f"- OS: {snapshot['os']}",
        f"- Uptime: {snapshot['uptime']}",
        f"- CPU: {_format_percent(snapshot.get('cpu_percent'))}",
        f"- Load avg: {_format_load(snapshot.get('load_average'))}",
        f"- Memory: {_format_memory(snapshot.get('memory', {}))}",
    ]
    for disk in snapshot.get("disks", []):
        lines.append(f"- Disk {disk['path']}: {_format_percent(disk.get('percent'))} used, {human_bytes(disk.get('free'))} free")
    if alerts:
        lines.append("Warnings:")
        lines.extend(f"- {alert}" for alert in alerts)
    else:
        lines.append("No immediate alerts based on default thresholds.")
    return "\n".join(lines)


def _cpu_answer(snapshot: dict) -> str:
    return "\n".join(
        [
            f"CPU Usage: {_format_percent(snapshot.get('cpu_percent'))}",
            f"Load avg: {_format_load(snapshot.get('load_average'))}",
            "Top CPU processes:",
            *_format_processes(snapshot.get("top_processes", []), limit=5),
        ]
    )


def _memory_answer(snapshot: dict) -> str:
    memory = snapshot.get("memory", {})
    return "\n".join(
        [
            f"Memory Usage: {_format_percent(memory.get('percent'))}",
            f"Used: {human_bytes(memory.get('used'))}",
            f"Available: {human_bytes(memory.get('available'))}",
            f"Total: {human_bytes(memory.get('total'))}",
        ]
    )


def _disk_answer(snapshot: dict) -> str:
    lines = ["Disk Status:"]
    for disk in snapshot.get("disks", []):
        lines.append(
            f"- {disk['path']}: {_format_percent(disk.get('percent'))} used, "
            f"{human_bytes(disk.get('free'))} free / {human_bytes(disk.get('total'))}"
        )
    return "\n".join(lines)


def _process_answer(snapshot: dict) -> str:
    return "\n".join(["Top CPU processes:", *_format_processes(snapshot.get("top_processes", []), limit=10)])


def _format_processes(processes: list[dict], limit: int) -> list[str]:
    if not processes:
        return ["- Could not read process information."]
    return [
        f"- pid={proc['pid']} cpu={proc['cpu']:.1f}% mem={proc['mem']:.1f}% cmd={proc['command']}"
        for proc in processes[:limit]
    ]


def _format_memory(memory: dict) -> str:
    return (
        f"{_format_percent(memory.get('percent'))} used "
        f"({human_bytes(memory.get('used'))} / {human_bytes(memory.get('total'))})"
    )


def _format_percent(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f}%"


def _format_load(value: tuple[float, float, float] | None) -> str:
    if not value:
        return "unknown"
    return ", ".join(f"{item:.2f}" for item in value)
