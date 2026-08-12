"""Run the MemOS MCP server over stdio: ``python -m memos.mcp``.

The stdio transport is the documented entry point (MCP.md section 9: trusted
local environment). The kernel is built from the default ``Settings``.
"""

from __future__ import annotations

from memos.mcp.server import create_mcp_server


def main() -> None:
    server = create_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = ["main"]