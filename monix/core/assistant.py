from __future__ import annotations

import json
import textwrap

from monix.config import Settings
from monix.llm.gemini import GeminiClient
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
            f"[현재 서버 스냅샷]\n{snapshot_text}\n"
            f"기본 로그 파일: {settings.log_file}\n"
            f"[등록된 로그 소스 (alias → path/container)]\n{registry_text}"
        )
        user_msg = {"role": "user", "parts": [{"text": user_text}]}

        # working copy of history for this agentic loop — never mutate history directly
        working: list[dict] = list((history or [])[-_MAX_HISTORY:]) + [user_msg]

        for _ in range(_MAX_TOOL_ROUNDS):
            text, tool_calls, raw_parts = client.chat_with_tools(working, TOOL_DECLARATIONS)

            if not tool_calls:
                # Final answer from the LLM
                _append_to_history(history, user_msg, text)
                return wrap(text or local_answer(question, snapshot))

            # Append the model's turn verbatim — raw_parts preserves thought_signature
            # and any other model-internal fields required by thinking-mode models.
            working.append({"role": "model", "parts": raw_parts})

            # Execute every requested tool and feed results back
            responses = []
            for tc in tool_calls:
                result = call_tool(tc.name, tc.args)
                responses.append(
                    {"functionResponse": {"name": tc.name, "response": {"result": result}}}
                )
            working.append({"role": "user", "parts": responses})

        # _MAX_TOOL_ROUNDS exhausted — ask the LLM to summarise what it found
        text, _, _ = client.chat_with_tools(working, [])
        _append_to_history(history, user_msg, text)
        return wrap(text or local_answer(question, snapshot))

    return wrap(local_answer(question, snapshot))


def _append_to_history(
    history: list[dict] | None,
    user_msg: dict,
    model_text: str | None,
) -> None:
    if history is None or not model_text or model_text.startswith("Gemini API"):
        return
    history.append(user_msg)
    history.append({"role": "model", "parts": [{"text": model_text}]})
    if len(history) > _MAX_HISTORY:
        del history[: len(history) - _MAX_HISTORY]


def local_answer(question: str, snapshot: dict | None = None) -> str:
    snapshot = snapshot or collect_snapshot()
    lowered = question.lower()
    if any(word in lowered for word in ("cpu", "load", "부하")):
        return _cpu_answer(snapshot)
    if any(word in lowered for word in ("memory", "mem", "ram", "메모리")):
        return _memory_answer(snapshot)
    if any(word in lowered for word in ("disk", "storage", "디스크", "용량")):
        return _disk_answer(snapshot)
    if any(word in lowered for word in ("process", "top", "프로세스")):
        return _process_answer(snapshot)
    return _summary_answer(snapshot)


def infer_service_name(tokens: list[str]) -> str | None:
    ignored = {"서비스", "service", "status", "상태", "확인", "알려줘", "보여줘", "체크", "해줘"}
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
        f"{snapshot['host']} 상태 요약",
        f"- OS: {snapshot['os']}",
        f"- Uptime: {snapshot['uptime']}",
        f"- CPU: {_format_percent(snapshot.get('cpu_percent'))}",
        f"- Load avg: {_format_load(snapshot.get('load_average'))}",
        f"- Memory: {_format_memory(snapshot.get('memory', {}))}",
    ]
    for disk in snapshot.get("disks", []):
        lines.append(f"- Disk {disk['path']}: {_format_percent(disk.get('percent'))} used, {human_bytes(disk.get('free'))} free")
    if alerts:
        lines.append("주의:")
        lines.extend(f"- {alert}" for alert in alerts)
    else:
        lines.append("현재 기본 임계치 기준의 즉시 경고는 없습니다.")
    return "\n".join(lines)


def _cpu_answer(snapshot: dict) -> str:
    return "\n".join(
        [
            f"CPU 사용률: {_format_percent(snapshot.get('cpu_percent'))}",
            f"Load avg: {_format_load(snapshot.get('load_average'))}",
            "CPU 상위 프로세스:",
            *_format_processes(snapshot.get("top_processes", []), limit=5),
        ]
    )


def _memory_answer(snapshot: dict) -> str:
    memory = snapshot.get("memory", {})
    return "\n".join(
        [
            f"메모리 사용률: {_format_percent(memory.get('percent'))}",
            f"사용 중: {human_bytes(memory.get('used'))}",
            f"사용 가능: {human_bytes(memory.get('available'))}",
            f"전체: {human_bytes(memory.get('total'))}",
        ]
    )


def _disk_answer(snapshot: dict) -> str:
    lines = ["디스크 상태:"]
    for disk in snapshot.get("disks", []):
        lines.append(
            f"- {disk['path']}: {_format_percent(disk.get('percent'))} used, "
            f"{human_bytes(disk.get('free'))} free / {human_bytes(disk.get('total'))}"
        )
    return "\n".join(lines)


def _process_answer(snapshot: dict) -> str:
    return "\n".join(["CPU 상위 프로세스:", *_format_processes(snapshot.get("top_processes", []), limit=10)])


def _format_processes(processes: list[dict], limit: int) -> list[str]:
    if not processes:
        return ["- 프로세스 정보를 읽을 수 없습니다."]
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
