from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from monix import __version__
from monix.tools.calling import TOOL_DECLARATIONS, call_tool


def mcp_tool_definitions() -> list[dict[str, Any]]:
    """Return Monix tools in MCP's tool-list shape.

    The source of truth stays in monix.tools.calling so CLI agent tool-calling
    and MCP expose the same read-only capabilities.
    """
    return [
        {
            "name": declaration["name"],
            "description": declaration.get("description", ""),
            "inputSchema": declaration.get("parameters", {"type": "object", "properties": {}}),
        }
        for declaration in TOOL_DECLARATIONS
    ]


def create_server():
    try:
        from mcp.server import Server
        from mcp.types import TextContent, Tool
    except ImportError as exc:
        raise RuntimeError(
            "The MCP server dependencies are not installed. "
            'Install them with: uv pip install -e ".[mcp]"'
        ) from exc

    server = Server("monix")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name=tool["name"],
                description=tool["description"],
                inputSchema=tool["inputSchema"],
            )
            for tool in mcp_tool_definitions()
        ]

    @server.call_tool()
    async def call_monix_tool(name: str, arguments: dict[str, Any] | None):
        result = call_tool(name, arguments or {})
        return [TextContent(type="text", text=result)]

    return server


async def run_stdio() -> None:
    try:
        from mcp.server.stdio import stdio_server
    except ImportError as exc:
        raise RuntimeError(
            "The MCP server dependencies are not installed. "
            'Install them with: uv pip install -e ".[mcp]"'
        ) from exc

    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="monix-mcp")
    parser.add_argument("--version", action="version", version=f"monix {__version__}")
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="MCP transport to use",
    )
    args = parser.parse_args(argv)

    try:
        if args.transport == "stdio":
            asyncio.run(run_stdio())
            return 0
    except RuntimeError as exc:
        print(f"monix-mcp: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
