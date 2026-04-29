import json

import monix.mcp as mcp_module
from monix.mcp import mcp_tool_definitions
from monix.tools.calling import TOOL_DECLARATIONS


def test_mcp_tool_definitions_reuse_common_tool_declarations():
    tools = mcp_tool_definitions()

    assert [tool["name"] for tool in tools] == [tool["name"] for tool in TOOL_DECLARATIONS]
    assert all("inputSchema" in tool for tool in tools)
    assert tools[0]["inputSchema"]["type"] == "object"
    assert "collect_snapshot" in {tool["name"] for tool in tools}
    assert "disk_info" in {tool["name"] for tool in tools}


def test_mcp_entrypoint_reports_runtime_error(monkeypatch, capsys):
    async def fail_stdio():
        raise RuntimeError('The MCP server dependencies are not installed. Install them with: uv pip install -e ".[mcp]"')

    monkeypatch.setattr(mcp_module, "run_stdio", fail_stdio)

    exit_code = mcp_module.main(["--transport", "stdio"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "uv pip install -e" in captured.err
    assert ".[mcp]" in captured.err


def test_unknown_mcp_tool_returns_json_error():
    from monix.tools.calling import call_tool

    result = json.loads(call_tool("does_not_exist", {}))

    assert result == {"error": "Unknown tool: does_not_exist"}


def test_system_tools_are_callable_through_common_registry():
    from monix.tools.calling import call_tool

    disk_result = json.loads(call_tool("disk_info", {"paths": ["/"]}))
    memory_result = json.loads(call_tool("memory_info", {}))

    assert isinstance(disk_result, list)
    assert disk_result[0]["path"] == "/"
    assert "percent" in memory_result
