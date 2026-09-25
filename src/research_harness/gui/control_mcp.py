"""MCP facade that forwards only managed GUI control operations."""
from __future__ import annotations
import argparse
from typing import Any
from .control import ControlClient
from .help import SYSTEM_PROMPT

READ_ACTIONS = {"workspace.list", "library.list", "collection.list", "run.status", "run.tasks", "queue.list", "queue.detail", "evidence.read", "report.read", "help.search", "help.read"}

class ManagedControlMCP:
    def __init__(self, descriptor: str) -> None: self.client = ControlClient(descriptor)
    def call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]: return self.client.call(action, payload)

def create_mcp_server(adapter: ManagedControlMCP) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        # MCP SDK 2.x renamed this public decorator/run facade to MCPServer.
        if exc.name != "mcp.server.fastmcp":
            raise RuntimeError("MCP SDK is required for managed GUI MCP") from exc
        try:
            from mcp.server.mcpserver import MCPServer as FastMCP
        except ModuleNotFoundError as inner:
            raise RuntimeError("MCP SDK is required for managed GUI MCP") from inner
    try:
        from mcp.types import ToolAnnotations
    except ModuleNotFoundError as exc:
        raise RuntimeError("MCP SDK is required for managed GUI MCP") from exc
    mcp = FastMCP("research-harness-gui-control", instructions=(
        "Before choosing a managed action, use help.search and help.read to consult the bundled GUI guidance. "
        "Forward only structured, scoped operations to the connected GUI; do not use shell tools or expose tokens. "
        "The following is product guidance supplied by this bridge, not a claim about the host's system role: " + SYSTEM_PROMPT))
    @mcp.tool(name="control", description="Call a scoped managed GUI control action.", annotations=ToolAnnotations(readOnlyHint=False))
    async def control(action: str, payload: dict[str, Any]) -> dict[str, Any]:
        return adapter.call(action, payload)
    return mcp

def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Managed Research Harness GUI MCP bridge")
    parser.add_argument("--descriptor", required=True)
    args=parser.parse_args(argv)
    adapter=ManagedControlMCP(args.descriptor)
    create_mcp_server(adapter).run(transport="stdio")
    return 0

if __name__ == "__main__": raise SystemExit(main())
