from __future__ import annotations

import datetime as _dt
import inspect
import json
from typing import Any, Mapping

from monix.llm import registry
from monix.llm.masker import mask_value
from monix.llm.types import ToolResponse


_TIMESTAMP_KEYS: tuple[str, ...] = ("measured_at", "timestamp", "time", "collected_at")


def invoke(
    name: str,
    args: Mapping[str, Any] | None,
    *,
    max_bytes: int,
) -> ToolResponse:
    """Execute a tool call and return a Gemini ``functionResponse`` part.

    The pipeline is: registry lookup → arg validation → call → JSON
    serialize → ``measured_at`` enrichment → size-cap truncation →
    masking. Any failure short-circuits to an ``error`` payload so the
    surrounding tool-calling loop can keep going.
    """
    arg_dict = dict(args or {})

    func = registry.get_tool(name)
    if func is None:
        return _error_response(name, f"unknown tool: {name}", max_bytes=max_bytes)

    try:
        bound = _bind(func, arg_dict)
    except TypeError as exc:
        return _error_response(name, f"invalid arguments: {exc}", max_bytes=max_bytes)

    try:
        result = func(**bound)
    except Exception as exc:  # noqa: BLE001 — feed back to the model as recoverable error
        return _error_response(
            name,
            f"{type(exc).__name__}: {exc}",
            max_bytes=max_bytes,
        )

    if inspect.isgenerator(result) or inspect.isasyncgen(result):
        return _error_response(
            name,
            "tool returned a stream which cannot be serialized",
            max_bytes=max_bytes,
        )

    payload = _to_jsonable(result)
    payload = _attach_measured_at(payload)
    payload = _truncate(payload, max_bytes=max_bytes)
    payload = mask_value(payload)
    return {"name": name, "response": payload}


def _bind(func, arg_dict: dict[str, Any]) -> dict[str, Any]:
    """Validate args against the function signature and return kwargs."""
    signature = inspect.signature(func)
    accepted: dict[str, Any] = {}
    missing: list[str] = []
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()
    )
    for param_name, param in signature.parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if param_name in arg_dict:
            accepted[param_name] = arg_dict[param_name]
        elif param.default is inspect.Parameter.empty:
            missing.append(param_name)
    if missing:
        raise TypeError(f"missing required argument(s): {', '.join(missing)}")
    extras = set(arg_dict) - set(accepted)
    if extras and not accepts_kwargs:
        raise TypeError(f"unexpected argument(s): {', '.join(sorted(extras))}")
    if accepts_kwargs:
        for key in extras:
            accepted[key] = arg_dict[key]
    return accepted


def _to_jsonable(value: Any) -> Any:
    """Make ``value`` JSON-safe without dropping its shape."""
    try:
        json.dumps(value)
        return value
    except TypeError:
        pass
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(v) for v in value]
    return repr(value)


def _attach_measured_at(payload: Any) -> Any:
    timestamp = _utc_now_iso()
    if isinstance(payload, dict):
        for key in _TIMESTAMP_KEYS:
            if payload.get(key):
                if "measured_at" not in payload:
                    payload["measured_at"] = payload[key]
                return payload
        payload["measured_at"] = timestamp
        return payload
    return {"measured_at": timestamp, "result": payload}


def _truncate(payload: Any, *, max_bytes: int) -> Any:
    serialized = json.dumps(payload, ensure_ascii=False)
    encoded = serialized.encode("utf-8")
    if len(encoded) <= max_bytes:
        return payload
    head = encoded[:max_bytes].decode("utf-8", errors="ignore")
    measured_at = payload.get("measured_at") if isinstance(payload, dict) else None
    truncated: dict[str, Any] = {
        "_truncated": True,
        "_original_size_bytes": len(encoded),
        "_preview": head,
    }
    if measured_at:
        truncated["measured_at"] = measured_at
    return truncated


def _error_response(name: str, message: str, *, max_bytes: int) -> ToolResponse:
    payload = {"error": message, "measured_at": _utc_now_iso()}
    payload = _truncate(payload, max_bytes=max_bytes)
    payload = mask_value(payload)
    return {"name": name, "response": payload}


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
