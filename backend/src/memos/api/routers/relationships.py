"""Relationship routes: add, list, and remove typed graph edges."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from memos.api.dependencies import RequestContext, get_request_context
from memos.api.schemas import AddRelationshipRequest, RelationshipOut


router = APIRouter(prefix="/memories", tags=["relationships"])


@router.get("/{memory_id}/relationships")
def get_relationships(
    memory_id: str,
    ctx: RequestContext = Depends(get_request_context),
    relationship_type: str | None = Query(default=None),
    direction: str = Query(default="any"),
):
    """Return relationships for a memory (optionally filtered by type/direction)."""
    relationships = ctx.kernel.get_relationships(
        memory_id=memory_id,
        relationship_type=relationship_type,
        direction=direction,
        principal_id=ctx.principal_id,
    )
    return ctx.success(
        [RelationshipOut.from_object(r).model_dump(mode="json") for r in relationships],
        metadata={"count": len(relationships)},
    )


@router.post("/{memory_id}/relationships")
def add_relationship(
    memory_id: str,
    body: AddRelationshipRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """Add a relationship from ``memory_id`` to ``target_id``."""
    relationship = ctx.kernel.add_relationship(
        source_id=memory_id,
        target_id=body.target_id,
        relationship_type=body.relationship_type,
        weight=body.weight,
        metadata=body.metadata,
        principal_id=ctx.principal_id,
    )
    return ctx.success(RelationshipOut.from_object(relationship).model_dump(mode="json"))


@router.delete("/{memory_id}/relationships/{relationship_id}")
def delete_relationship(
    memory_id: str,
    relationship_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Delete a specific relationship."""
    ctx.kernel.remove_relationship(relationship_id, principal_id=ctx.principal_id)
    return ctx.success({"memory_id": memory_id, "relationship_id": relationship_id, "deleted": True})