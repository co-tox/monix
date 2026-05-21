from __future__ import annotations

from typing import Iterable, Optional, Protocol

from monix.llm.types import History, ToolSchema, UsageInfo


class LLMClient(Protocol):
    @property
    def enabled(self) -> bool: ...

    def chat(self, history: History) -> Optional[str]: ...

    def chat_with_tools(
        self,
        history: History,
        tools: Iterable[ToolSchema],
    ) -> tuple[dict, UsageInfo]: ...
