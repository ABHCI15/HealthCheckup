"""MCP stdio server exposing HealthCheckup's tools. Run: python mcp_server.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from healthcheck import tools  # noqa: E402

mcp = _Server(
    "healthcheckup",
    instructions=(
        "Check a food, supplement or medicine for recalls and for protein-level food-drug "
        "interactions. Never describe a product as safe: say what was found in the sources "
        "that answered, and name the sources."
    ),
)

for _fn in tools.TOOLS.values():
    mcp.add_tool(_fn)  # name and description come from the function and its docstring


if __name__ == "__main__":
    mcp.run()
