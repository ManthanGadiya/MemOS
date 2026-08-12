"""Application factory for the MemOS MCP server.

``create_mcp_server`` assembles a FastMCP server that owns exactly one kernel
instance and exposes the twelve documented tools (MCP.md section 4) plus the
read-only resources (MCP.md section 7). The kernel is injected for the
integration test suite, or built through the single ``build_kernel`` factory
when omitted. The server is presentation-only: no business logic lives here.
"""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from memos.config.settings import Settings
from memos.kernel.factory import build_kernel
from memos.kernel.kernel import MemoryKernel
from memos.mcp.resources import register_resources
from memos.mcp.tools import McpTools

_INSTRUCTIONS = (
    "MemOS MCP server. Every tool maps to a single Memory Kernel operation and "
    "returns a deterministic envelope: {\"success\": true, \"data\": ...} on "
    "success, or {\"success\": false, \"error\": {code, message, details}} with "
    "one of INVALID_INPUT, MEMORY_NOT_FOUND, PERMISSION_DENIED, STORAGE_FAILURE, "
    "INTERNAL_ERROR on failure."
)

# MCP tool name -> short description (MCP.md section 4).
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "create_memory": "Create a new Memory Object.",
    "get_memory": "Retrieve a Memory Object by ID.",
    "search_memory": "Run hybrid retrieval and return ranked Memory Objects.",
    "update_memory": "Create a new version of a Memory Object.",
    "delete_memory": "Soft-delete a Memory Object.",
    "archive_memory": "Archive a Memory Object.",
    "list_memories": "List stored memories with optional filters.",
    "list_versions": "Return the version history for a Memory Object.",
    "create_relationship": "Link two memories with a typed relationship.",
    "delete_relationship": "Remove a relationship by ID.",
    "related_memories": "Return relationships connected to a Memory Object.",
    "system_health": "Return kernel, storage, and MCP health status.",
}


def create_mcp_server(
    kernel: Optional[MemoryKernel] = None,
    settings: Optional[Settings] = None,
) -> FastMCP:
    """Create the MemOS MCP server.

    Args:
        kernel: Optional pre-built kernel. When ``None``, one is built from
            ``settings`` using :func:`build_kernel`.
        settings: Optional runtime configuration. When ``None`` a default
            :class:`Settings` is built (honouring ``MEMOS_`` env vars).

    Returns:
        A configured :class:`FastMCP` server with all tools and resources
        registered.
    """
    configured = settings if settings is not None else Settings()
    instance = kernel if kernel is not None else build_kernel(configured)

    server = FastMCP(
        name=configured.app_name,
        instructions=_INSTRUCTIONS,
    )

    tools = McpTools(instance)
    for tool_name, description in _TOOL_DESCRIPTIONS.items():
        server.tool(name=tool_name, description=description)(
            getattr(tools, tool_name)
        )

    register_resources(server, instance)
    return server


__all__ = ["create_mcp_server"]