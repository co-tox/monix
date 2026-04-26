from __future__ import annotations

import json
from typing import Any

from monix.llm.types import History, Message


RECENT_TURNS_KEEP = 2
"""How many trailing user→model pairs to always preserve.

Set conservatively so an in-progress tool-calling pair is never cut.
"""

_BYTES_PER_TOKEN_ESTIMATE = 4


def _is_user_text_start(message: Message) -> bool:
    """A pair begins on a user message whose first part is plain text."""
    if not isinstance(message, dict):
        return False
    if message.get("role") != "user":
        return False
    parts = message.get("parts") or []
    if not parts:
        return False
    first = parts[0]
    if not isinstance(first, dict):
        return False
    return "text" in first and "functionResponse" not in first


def _pair_indices(history: History) -> list[tuple[int, int]]:
    """Return ``[(start, end_exclusive), ...]`` for each user→model pair.

    Anything before the first user-text message is treated as a "preamble"
    and never trimmed (no pair entry is emitted for it).
    """
    starts: list[int] = [i for i, msg in enumerate(history) if _is_user_text_start(msg)]
    if not starts:
        return []
    pairs: list[tuple[int, int]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(history)
        pairs.append((start, end))
    return pairs


def _estimate_tokens(messages: list[Message]) -> int:
    try:
        size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        size = sum(len(str(m)) for m in messages)
    return max(size // _BYTES_PER_TOKEN_ESTIMATE, 1)


def maybe_trim(
    history: History,
    total_tokens: int,
    budget: int,
    *,
    recent_keep: int = RECENT_TURNS_KEEP,
) -> int:
    """Drop oldest user→model pairs from ``history`` if over the budget.

    ``history`` is mutated in-place. Returns the (estimated) token count
    after trimming so the caller can keep tracking the running total.
    The most recent ``recent_keep`` pairs are always preserved.
    """
    if budget <= 0 or total_tokens <= budget:
        return total_tokens

    estimated = total_tokens
    while estimated > budget:
        pairs = _pair_indices(history)
        if len(pairs) <= recent_keep:
            break
        start, end = pairs[0]
        removed = history[start:end]
        del history[start:end]
        saving = _estimate_tokens(removed)
        estimated = max(estimated - saving, 0)
    return estimated
