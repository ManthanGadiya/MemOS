"""System routes: health, runtime status, dashboard statistics, config."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from memos.api.dependencies import RequestContext, get_request_context
from memos.kernel.audit import AuditResult
from memos.kernel.operations import KernelOperation


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


@router.get("/dashboard/health")
def dashboard_health(ctx: RequestContext = Depends(get_request_context)):
    """Return dashboard-oriented health: liveness plus runtime identity."""
    settings = ctx.kernel.settings
    kernel_health = ctx.kernel.health()
    status = "ok" if all(v == "ok" for v in kernel_health.values()) else "degraded"
    return ctx.success(
        {
            "status": status,
            "app": settings.app_name,
            "version": settings.version,
            "storage_backend": settings.storage_backend,
            "embedding_backend": settings.embedding_backend,
            **kernel_health,
        }
    )


@router.get("/dashboard/logs")
def dashboard_logs(
    ctx: RequestContext = Depends(get_request_context),
    operation: Optional[str] = Query(default=None, description="KernelOperation value"),
    result: Optional[str] = Query(default=None, description="AuditResult value"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return recent audit records for the dashboard.

    The audit log is the dashboard's ``Logs`` module data source (API.md
    section 9). Filters are validated against the canonical enums so unknown
    values produce ``INVALID_REQUEST`` instead of reaching the kernel.
    """
    kernel_operation: Optional[KernelOperation] = None
    if operation is not None:
        try:
            kernel_operation = KernelOperation(operation)
        except ValueError:
            valid = ", ".join(op.value for op in KernelOperation)
            return ctx.error(
                "INVALID_REQUEST",
                f"unknown operation '{operation}'; valid values: {valid}",
            )

    audit_result: Optional[AuditResult] = None
    if result is not None:
        try:
            audit_result = AuditResult(result)
        except ValueError:
            valid = ", ".join(res.value for res in AuditResult)
            return ctx.error(
                "INVALID_REQUEST",
                f"unknown result '{result}'; valid values: {valid}",
            )

    records = ctx.kernel.list_audit(
        operation=kernel_operation,
        result=audit_result,
        limit=limit,
        offset=offset,
    )
    return ctx.success(
        {
            "records": [record.to_dict() for record in records],
            "total": ctx.kernel.statistics()["audit_count"],
        }
    )


@router.get("/config")
def config(ctx: RequestContext = Depends(get_request_context)):
    """Return a safe subset of the runtime configuration."""
    settings = ctx.kernel.settings
    return ctx.success({key: getattr(settings, key) for key in _SAFE_CONFIG_KEYS})