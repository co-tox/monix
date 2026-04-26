from monix.tools.calling import TOOL_DECLARATIONS

# All tools exposed via function calling are read-only by design.
# Legacy names kept for backward compatibility.
_LEGACY_READ_ONLY = frozenset({"snapshot", "top_processes"})
_TOOL_NAMES = frozenset(d["name"] for d in TOOL_DECLARATIONS)

READ_ONLY_TOOLS = _LEGACY_READ_ONLY | _TOOL_NAMES


def is_read_only_tool(name: str) -> bool:
    return name in READ_ONLY_TOOLS
