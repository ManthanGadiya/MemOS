"""Route aggregators for the MemOS REST API."""

from fastapi import APIRouter

from memos.api.routers import (
    memories,
    relationships,
    search,
    system,
    versions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(memories.router)
api_router.include_router(search.router)
api_router.include_router(relationships.router)
api_router.include_router(versions.router)
api_router.include_router(system.router)

__all__ = ["api_router"]