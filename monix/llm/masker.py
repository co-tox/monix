from __future__ import annotations

import re
from typing import Any


_MASK = "***"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    # API key / secret / token / password keyword + value
    re.compile(r"""(?i)(api[_-]?key|secret|token|password)["'\s:=]+\S+"""),
    # JWT
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    # Long hex token (32+ chars)
    re.compile(r"[a-f0-9]{32,}"),
    # AWS Access Key
    re.compile(r"AKIA[0-9A-Z]{16}"),
)


def mask_text(text: str) -> str:
    """Apply every sensitive-data regex to ``text`` and return the masked result."""
    if not text:
        return text
    masked = text
    for pattern in _PATTERNS:
        masked = pattern.sub(_MASK, masked)
    return masked


def mask_value(value: Any) -> Any:
    """Recursively walk JSON-like data and mask sensitive substrings.

    - Strings are passed through ``mask_text``.
    - Containers (dict/list/tuple) are walked structurally so masking
      applies to nested string fields.
    - Other scalars are returned unchanged.
    """
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(mask_value(v) for v in value)
    return value
