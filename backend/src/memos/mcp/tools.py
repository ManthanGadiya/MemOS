"""MCP tool implementations for MemOS.

Every tool is a thin translation layer between the MCP request and one Memory
Kernel operation (``docs/MCP.md`` section 6). Tools hold a reference to the
injected kernel, coerce string arguments to domain enums, and return the
deterministic result envelope from :mod:`memos.mcp.errors`. No business logic
lives here by design.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from memos.api.schemas import (
    MemoryOut,
    MemoryVersionOut,
    RelationshipOut,
    SearchResultOut,
)
from memos.domain.memory import LifecycleState, MemoryType, PermissionLevel
from memos.domain.relationship import RelationshipType
from memos.engines.permission import SYSTEM_PRINCIPAL
from memos.kernel.kernel import MemoryKernel
from memos.mcp.errors import call_kernel


def _coerce_memory_type(value: Optional[str]) -> Optional[MemoryType]:
    if value is None:
        return None
    try:
        return MemoryType(value)
    except ValueError as exc:
        raise ValueError(
            f"invalid memory_type: {value!r}; expected one of {[e.value for e in MemoryType]}"
        ) from exc


def _coerce_state(value: Optional[str]) -> Optional[LifecycleState]:
    if value is None:
        return None
    try:
        return LifecycleState(value)
    except ValueError as exc:
        raise ValueError(
            f"invalid state: {value!r}; expected one of {[e.value for e in LifecycleState]}"
        ) from exc


def _coerce_relationship_type(value: str) -> RelationshipType:
    try:
        return RelationshipType(value)
    except ValueError as exc:
        raise ValueError(
            f"invalid relationship_type: {value!r}; expected one of "
            f"{[e.value for e in RelationshipType]}"
        ) from exc


class McpTools:
    """The twelve MCP tools exposed by the MemOS server (MCP.md section 4)."""

    def __init__(self, kernel: MemoryKernel) -> None:
        self._kernel = kernel
        self._principal = SYSTEM_PRINCIPAL

    def create_memory(
        self,
        content: str,
        title: str = "",
        memory_type: str = "semantic",
        owner_id: str = "default",
        namespace: str = "personal",
        source: str = "",
        summary: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new Memory Object."""
        memory = call_kernel(
            lambda: self._kernel.create(
                content=content,
                owner_id=owner_id,
                memory_type=_coerce_memory_type(memory_type) or MemoryType.SEMANTIC,
                namespace=namespace,
                title=title,
                source=source,
                summary=summary,
                tags=tags,
                metadata=metadata,
                principal_id=self._principal,
            )
        )
        if memory["success"]:
            memory["data"] = {
                "memory": MemoryOut.from_object(memory["data"]).model_dump(mode="json"),
                "status": "created",
            }
        return memory

    def get_memory(self, memory_id: str) -> Dict[str, Any]:
        """Return a single Memory Object by ID."""
        memory = call_kernel(
            lambda: self._kernel.get(memory_id, principal_id=self._principal)
        )
        if memory["success"]:
            memory["data"] = MemoryOut.from_object(memory["data"]).model_dump(mode="json")
        return memory

    def search_memory(
        self,
        query: str,
        top_k: Optional[int] = None,
        owner_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        state: Optional[str] = None,
        tags: Optional[List[str]] = None,
        graph_expansion: bool = False,
    ) -> Dict[str, Any]:
        """Run hybrid retrieval and return ranked Memory Objects."""
        results = call_kernel(
            lambda: self._kernel.search(
                query=query,
                top_k=top_k,
                owner_id=owner_id,
                memory_type=_coerce_memory_type(memory_type),
                state=_coerce_state(state),
                tags=tags,
                principal_id=self._principal,
                graph_expansion=graph_expansion,
            )
        )
        if results["success"]:
            scored = results["data"]
            results["data"] = {
                "results": [SearchResultOut.from_object(r).model_dump(mode="json") for r in scored],
                "count": len(scored),
            }
        return results

    def update_memory(
        self,
        memory_id: str,
        content: Optional[str] = None,
        title: Optional[str] = None,
        source: Optional[str] = None,
        summary: Optional[str] = None,
        namespace: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new version of a Memory Object with the changed fields."""
        fields: Dict[str, Any] = {}
        if content is not None:
            fields["content"] = content
        if title is not None:
            fields["title"] = title
        if source is not None:
            fields["source"] = source
        if summary is not None:
            fields["summary"] = summary
        if namespace is not None:
            fields["namespace"] = namespace
        if memory_type is not None:
            fields["memory_type"] = _coerce_memory_type(memory_type)
        if tags is not None:
            fields["tags"] = tags
        if metadata is not None:
            fields["metadata"] = metadata

        memory = call_kernel(
            lambda: self._kernel.update(memory_id, principal_id=self._principal, **fields)
        )
        if memory["success"]:
            memory["data"] = MemoryOut.from_object(memory["data"]).model_dump(mode="json")
        return memory

    def delete_memory(self, memory_id: str) -> Dict[str, Any]:
        """Soft-delete a Memory Object (terminal DELETED state)."""
        result = call_kernel(
            lambda: self._kernel.delete(memory_id, principal_id=self._principal)
        )
        if result["success"]:
            result["data"] = {"memory_id": memory_id, "deleted": True}
        return result

    def archive_memory(self, memory_id: str) -> Dict[str, Any]:
        """Move a Memory Object to ARCHIVED (excluded from default retrieval)."""
        memory = call_kernel(
            lambda: self._kernel.archive(memory_id, principal_id=self._principal)
        )
        if memory["success"]:
            memory["data"] = {
                "memory": MemoryOut.from_object(memory["data"]).model_dump(mode="json"),
                "status": "archived",
            }
        return memory

    def list_memories(
        self,
        owner_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        state: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Return a paginated list of memories, optionally filtered."""
        result = call_kernel(
            lambda: self._kernel.list_memories(
                owner_id=owner_id,
                memory_type=_coerce_memory_type(memory_type),
                state=_coerce_state(state),
                tags=tags,
                limit=limit,
                offset=offset,
                principal_id=self._principal,
            )
        )
        if result["success"]:
            memories = result["data"]
            result["data"] = {
                "memories": [MemoryOut.from_object(m).model_dump(mode="json") for m in memories],
                "count": len(memories),
            }
        return result

    def list_versions(self, memory_id: str) -> Dict[str, Any]:
        """Return the full version history for a Memory Object."""
        result = call_kernel(
            lambda: self._kernel.list_versions(memory_id, principal_id=self._principal)
        )
        if result["success"]:
            versions = result["data"]
            result["data"] = {
                "versions": [MemoryVersionOut.from_object(v).model_dump(mode="json") for v in versions],
                "count": len(versions),
            }
        return result

    def create_relationship(
        self,
        source_memory: str,
        target_memory: str,
        relationship_type: str = "related_to",
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add a typed relationship from one memory to another."""
        relationship = call_kernel(
            lambda: self._kernel.add_relationship(
                source_id=source_memory,
                target_id=target_memory,
                relationship_type=_coerce_relationship_type(relationship_type),
                weight=weight,
                metadata=metadata,
                principal_id=self._principal,
            )
        )
        if relationship["success"]:
            relationship["data"] = RelationshipOut.from_object(
                relationship["data"]
            ).model_dump(mode="json")
        return relationship

    def delete_relationship(self, relationship_id: str) -> Dict[str, Any]:
        """Remove a relationship by ID."""
        result = call_kernel(
            lambda: self._kernel.remove_relationship(relationship_id, principal_id=self._principal)
        )
        if result["success"]:
            result["data"] = {"relationship_id": relationship_id, "deleted": True}
        return result

    def related_memories(
        self,
        memory_id: str,
        relationship_type: Optional[str] = None,
        direction: str = "any",
    ) -> Dict[str, Any]:
        """Return relationships connected to a Memory Object."""
        result = call_kernel(
            lambda: self._kernel.get_relationships(
                memory_id=memory_id,
                relationship_type=relationship_type,
                direction=direction,
                principal_id=self._principal,
            )
        )
        if result["success"]:
            relationships = result["data"]
            result["data"] = {
                "relationships": [
                    RelationshipOut.from_object(r).model_dump(mode="json") for r in relationships
                ],
                "count": len(relationships),
            }
        return result

    def system_health(self) -> Dict[str, Any]:
        """Return kernel, storage, and MCP health status."""
        kernel_health = call_kernel(lambda: self._kernel.health())
        if not kernel_health["success"]:
            return kernel_health
        statuses = kernel_health["data"]
        status = "ok" if all(v == "ok" for v in statuses.values()) else "degraded"
        return {
            "success": True,
            "data": {
                "status": status,
                "kernel": statuses.get("kernel", "unknown"),
                "storage": statuses.get("metadata_store", "unknown"),
                "mcp": "ok",
            },
        }


__all__ = ["McpTools"]