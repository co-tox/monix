from __future__ import annotations

import inspect
import typing
from typing import Any, Callable, Optional

import monix.tools as _tools

from monix.llm.types import ToolSchema


EXCLUDED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "human_bytes",
        "human_duration",
        "build_alerts",
    }
)


_PRIMITIVE_MAP: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}


def _origin_to_json_type(origin: Any) -> Optional[str]:
    if origin is None:
        return None
    if origin in (list, tuple, set, frozenset):
        return "array"
    if origin in (dict,):
        return "object"
    try:
        import collections.abc as _abc
    except ImportError:  # pragma: no cover - stdlib always present
        return None
    if origin in (_abc.Iterable, _abc.Sequence, _abc.MutableSequence, _abc.Set, _abc.MutableSet):
        return "array"
    if origin in (_abc.Mapping, _abc.MutableMapping):
        return "object"
    return None


def _annotation_to_json_type(annotation: Any) -> str:
    """Map a Python annotation to a JSON-schema primitive type string.

    Falls back to ``"string"`` whenever the annotation is unknown.
    """
    if annotation is inspect.Parameter.empty or annotation is None:
        return "string"

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is typing.Union:
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _annotation_to_json_type(non_none[0])
        return "string"

    if isinstance(annotation, type):
        if annotation in _PRIMITIVE_MAP:
            return _PRIMITIVE_MAP[annotation]
        if issubclass(annotation, (list, tuple, set, frozenset)):
            return "array"
        if issubclass(annotation, dict):
            return "object"
        return "string"

    json_type = _origin_to_json_type(origin)
    if json_type is not None:
        return json_type

    return "string"


def _resolve_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(func)
    except Exception:
        return {}


def _build_schema(name: str, func: Callable[..., Any]) -> ToolSchema:
    signature = inspect.signature(func)
    hints = _resolve_hints(func)

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []

    for param_name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = hints.get(param_name, param.annotation)
        json_type = _annotation_to_json_type(annotation)
        prop: dict[str, Any] = {"type": json_type}
        if json_type == "array":
            prop["items"] = {"type": "string"}
        properties[param_name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters_schema["required"] = required

    description = (inspect.getdoc(func) or "").strip()

    return {
        "name": name,
        "description": description,
        "parameters": parameters_schema,
    }


def _discover() -> tuple[dict[str, Callable[..., Any]], list[ToolSchema]]:
    funcs: dict[str, Callable[..., Any]] = {}
    schemas: list[ToolSchema] = []
    exposed = getattr(_tools, "__all__", None)
    if not exposed:
        return funcs, schemas
    for name in exposed:
        if name in EXCLUDED_TOOL_NAMES:
            continue
        target = getattr(_tools, name, None)
        if target is None or not callable(target):
            continue
        funcs[name] = target
        schemas.append(_build_schema(name, target))
    return funcs, schemas


_FUNCTIONS, _SCHEMAS = _discover()


def list_tools() -> list[ToolSchema]:
    """Return the cached `function_declarations` list for Gemini."""
    return list(_SCHEMAS)


def get_tool(name: str) -> Optional[Callable[..., Any]]:
    """Look up a registered tool callable by name."""
    return _FUNCTIONS.get(name)


def tool_names() -> list[str]:
    return list(_FUNCTIONS.keys())
