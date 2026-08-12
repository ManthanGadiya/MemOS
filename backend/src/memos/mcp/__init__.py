"""MCP server layer for MemOS.

Presentation only: every tool validates its input, delegates the operation to
the Memory Kernel, and maps the result to the MCP error vocabulary
(``docs/MCP.md`` section 8). No business logic and no engine imports live
here.
"""

from memos.mcp.server import create_mcp_server

__all__ = ["create_mcp_server"]