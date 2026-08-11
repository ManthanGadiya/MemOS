"""Search route: hybrid retrieval through the kernel."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from memos.api.dependencies import RequestContext, get_request_context
from memos.api.schemas import SearchRequest, SearchResultOut


router = APIRouter(prefix="/search", tags=["search"])


@router.post("")
def search(
    body: SearchRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """Execute a hybrid retrieval search against the memory store."""
    results = ctx.kernel.search(
        query=body.query,
        top_k=body.top_k,
        owner_id=body.owner_id,
        memory_type=body.memory_type,
        state=body.state,
        tags=body.tags,
        graph_expansion=body.graph_expansion,
        principal_id=ctx.principal_id,
    )
    return ctx.success(
        [SearchResultOut.from_object(r).model_dump(mode="json") for r in results],
        metadata={"count": len(results)},
    )