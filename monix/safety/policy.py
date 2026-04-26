READ_ONLY_TOOLS = frozenset({"snapshot", "top_processes", "tail_log", "service_status"})


def is_read_only_tool(name: str) -> bool:
    return name in READ_ONLY_TOOLS
