"""Version history routes: read-only snapshots of a memory's chain."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from memos.api.dependencies import RequestContext, get_request_context
from memos.api.schemas import MemoryVersionOut


router = APIRouter(prefix="/memories", tags=["versions"])


@router.get("/{memory_id}/versions")
def list_versions(
    memory_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return the version history for a memory (oldest first)."""
    versions = ctx.kernel.list_versions(memory_id, principal_id=ctx.principal_id)
    return ctx.success(
        [MemoryVersionOut.from_object(v).model_dump(mode="json") for v in versions],
        metadata={"count": len(versions)},
    )


@router.get("/{memory_id}/versions/{version}")
def get_version(
    memory_id: str,
    version: int,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return a single version snapshot for a memory."""
    snapshot = ctx.kernel.get_version(memory_id, version, principal_id=ctx.principal_id)
    return ctx.success(MemoryVersionOut.from_object(snapshot).model_dump(mode="json"))