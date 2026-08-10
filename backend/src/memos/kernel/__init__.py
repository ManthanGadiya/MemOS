"""Memory Kernel package.

Public exports for the REST API, MCP server, and integration tests.
"""

from __future__ import annotations

from .audit import AuditRecord, AuditResult, AuditStore, InMemoryAuditStore
from .errors import KernelError, KernelErrorCode, to_kernel_error
from .events import EventBus, InMemoryEventBus, KernelEvent, event_kind
from .factory import build_kernel
from .kernel import MemoryKernel
from .operations import KernelOperation
from .transaction import MemorySnapshot, Transaction, TransactionStatus
from .validation import RequestValidator

__all__ = [
    "AuditRecord",
    "AuditResult",
    "AuditStore",
    "InMemoryAuditStore",
    "KernelError",
    "KernelErrorCode",
    "to_kernel_error",
    "EventBus",
    "InMemoryEventBus",
    "KernelEvent",
    "event_kind",
    "build_kernel",
    "MemoryKernel",
    "KernelOperation",
    "MemorySnapshot",
    "Transaction",
    "TransactionStatus",
    "RequestValidator",
]