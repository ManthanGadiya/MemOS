"""Read-only MCP resources for MemOS.

``docs/MCP.md`` section 7: resources provide contextual information without
modifying memory. Every resource renders JSON text through the same
deterministic envelope used by tools, and never mutates kernel state.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from mcp.server.fastmcp import FastMCP

from memos.api.schemas import MemoryOut, MemoryVersionOut, RelationshipOut
from memos.engines.permission import SYSTEM_PRINCIPAL
from memos.kernel.kernel import MemoryKernel
from memos.mcp.errors import call_kernel

# Runtime settings that are safe to expose as a resource (mirrors the REST
# API's safe-config list in api/routers/system.py: never the database path,
# data directory, or any credential-adjacent value).
_SAFE_CONFIG_KEYS: tuple[str, ...] = (
    "app_name",
    "version",
    "debug",
    "storage_backend",
    "embedding_backend",
    "vector_store_backend",
    "graph_store_backend",
    "embedding_dimension",
    "default_top_k",
    "default_permission",
    "log_level",
)


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _resource(handler: Callable[[], Any]) -> str:
    """Run a read-only handler and render its result as JSON text."""
    result = call_kernel(handler)
    return _json(result)


def register_resources(server: FastMCP, kernel: MemoryKernel) -> None:
    """Attach the documented read-only resources to the MCP server."""

    @server.resource("memos://memory/{memory_id}")
    def memory_resource(memory_id: str) -> str:
        """A single Memory Object by ID."""
        return _resource(
            lambda: MemoryOut.from_object(
                kernel.get(memory_id, principal_id=SYSTEM_PRINCIPAL)
            ).model_dump(mode="json")
        )

    @server.resource("memos://memory/{memory_id}/versions")
    def memory_versions_resource(memory_id: str) -> str:
        """Version history for a Memory Object."""
        return _resource(
            lambda: [
                MemoryVersionOut.from_object(v).model_dump(mode="json")
                for v in kernel.list_versions(memory_id, principal_id=SYSTEM_PRINCIPAL)
            ]
        )

    @server.resource("memos://memory/{memory_id}/relationships")
    def memory_relationships_resource(memory_id: str) -> str:
        """Relationships connected to a Memory Object."""
        return _resource(
            lambda: [
                RelationshipOut.from_object(r).model_dump(mode="json")
                for r in kernel.get_relationships(
                    memory_id=memory_id, principal_id=SYSTEM_PRINCIPAL
                )
            ]
        )

    @server.resource("memos://statistics")
    def statistics_resource() -> str:
        """Aggregate system statistics (no memory content)."""
        return _resource(lambda: kernel.statistics())

    @server.resource("memos://config")
    def config_resource() -> str:
        """A safe subset of the runtime configuration."""
        settings = kernel.settings
        return _resource(
            lambda: {key: getattr(settings, key) for key in _SAFE_CONFIG_KEYS}
        )

    @server.resource("memos://health")
    def health_resource() -> str:
        """Kernel and store health status."""
        return _resource(lambda: kernel.health())


__all__ = ["register_resources"]