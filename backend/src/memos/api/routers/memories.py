"""Memory routes: CRUD plus archive/restore lifecycle transitions."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from memos.api.dependencies import RequestContext, get_request_context
from memos.api.schemas import (
    CreateMemoryRequest,
    MemoryOut,
    UpdateMemoryRequest,
)
from memos.domain.memory import LifecycleState, MemoryType


router = APIRouter(prefix="/memories", tags=["memories"])


@router.post("")
def create_memory(
    body: CreateMemoryRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """Create a new Memory Object."""
    memory = ctx.kernel.create(
        content=body.content,
        owner_id=body.owner_id,
        memory_type=body.memory_type or MemoryType.SEMANTIC,
        namespace=body.namespace,
        title=body.title,
        source=body.source,
        summary=body.summary,
        tags=body.tags,
        metadata=body.metadata,
        permission=body.permission,
        principal_id=ctx.principal_id,
    )
    return ctx.success(MemoryOut.from_object(memory).model_dump(mode="json"))


@router.get("/{memory_id}")
def get_memory(
    memory_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return a single Memory Object."""
    memory = ctx.kernel.get(memory_id, principal_id=ctx.principal_id)
    return ctx.success(MemoryOut.from_object(memory).model_dump(mode="json"))


@router.put("/{memory_id}")
def update_memory(
    memory_id: str,
    body: UpdateMemoryRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """Create a new version of the Memory Object with the changed fields."""
    fields = body.model_dump(exclude_unset=True)
    memory = ctx.kernel.update(
        memory_id,
        principal_id=ctx.principal_id,
        **fields,
    )
    return ctx.success(MemoryOut.from_object(memory).model_dump(mode="json"))


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Soft-delete: marks the Memory Object as DELETED (terminal)."""
    ctx.kernel.delete(memory_id, principal_id=ctx.principal_id)
    return ctx.success({"memory_id": memory_id, "deleted": True})


@router.put("/{memory_id}/archive")
def archive_memory(
    memory_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Move the Memory Object to ARCHIVED (excluded from default retrieval)."""
    memory = ctx.kernel.archive(memory_id, principal_id=ctx.principal_id)
    return ctx.success(MemoryOut.from_object(memory).model_dump(mode="json"))


@router.put("/{memory_id}/restore")
def restore_memory(
    memory_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Restore the Memory Object to ACTIVE."""
    memory = ctx.kernel.restore(memory_id, principal_id=ctx.principal_id)
    return ctx.success(MemoryOut.from_object(memory).model_dump(mode="json"))


@router.get("")
def list_memories(
    ctx: RequestContext = Depends(get_request_context),
    owner_id: Optional[str] = Query(default=None),
    memory_type: Optional[MemoryType] = Query(default=None),
    state: Optional[LifecycleState] = Query(default=None),
    tags: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return a paginated list of memories, optionally filtered."""
    memories = ctx.kernel.list_memories(
        owner_id=owner_id,
        memory_type=memory_type,
        state=state,
        tags=tags,
        limit=limit,
        offset=offset,
        principal_id=ctx.principal_id,
    )
    return ctx.success(
        [MemoryOut.from_object(m).model_dump(mode="json") for m in memories],
        metadata={"limit": limit, "offset": offset},
    )