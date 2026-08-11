"""System routes: health, runtime status, dashboard statistics, config."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from memos.api.dependencies import RequestContext, get_request_context


router = APIRouter(tags=["system"])


# Runtime settings that are safe to expose to clients (never the database
# path, data directory, or any credential-adjacent value).
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


@router.get("/health")
def health(ctx: RequestContext = Depends(get_request_context)):
    """Return machine-readable health."""
    kernel_health = ctx.kernel.health()
    status = "ok" if all(v == "ok" for v in kernel_health.values()) else "degraded"
    return ctx.success({"status": status, **kernel_health})


@router.get("/system/status")
def system_status(ctx: RequestContext = Depends(get_request_context)):
    """Return runtime information about the kernel and stores."""
    settings = ctx.kernel.settings
    return ctx.success(
        {
            "app": settings.app_name,
            "version": settings.version,
            "storage_backend": settings.storage_backend,
            "embedding_backend": settings.embedding_backend,
            "vector_store_backend": settings.vector_store_backend,
            "graph_store_backend": settings.graph_store_backend,
            "statistics": ctx.kernel.statistics(),
        }
    )


@router.get("/dashboard/statistics")
def dashboard_statistics(ctx: RequestContext = Depends(get_request_context)):
    """Return aggregate system statistics for the dashboard."""
    return ctx.success(ctx.kernel.statistics())


@router.get("/config")
def config(ctx: RequestContext = Depends(get_request_context)):
    """Return a safe subset of the runtime configuration."""
    settings = ctx.kernel.settings
    return ctx.success({key: getattr(settings, key) for key in _SAFE_CONFIG_KEYS})