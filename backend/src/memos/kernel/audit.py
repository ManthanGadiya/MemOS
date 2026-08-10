"""Immutable audit logging for the Memory Kernel.

Security.md section 7 requires every important operation to generate an
audit record capturing Timestamp, Request ID, Memory ID, Operation, User/Agent,
and Result. SRS section 10.17 additionally records ``created_by``,
``modified_by``, ``modified_at``, and ``operation``. Audit logs are immutable.

:class:`AuditRecord` is a frozen dataclass (nothing can mutate an existing
record) and :class:`InMemoryAuditStore` appends without ever altering prior
entries. The :class:`AuditStore` interface deliberately mirrors the shape of
the ``audit_logs`` table (see docs/Database.md) so a future SQLite/Postgres
adapter can implement the same contract without kernel changes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Protocol

from memos.domain.memory import now_utc
from memos.kernel.operations import KernelOperation


class AuditResult(str, Enum):
    """Terminal outcome recorded for an audited operation."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    ROLLBACK = "ROLLBACK"
    DENIED = "DENIED"


@dataclass(frozen=True)
class AuditRecord:
    """A single immutable audit entry.

    All fields are required and reflect the documented audit contract. The
    dataclass is frozen, so the only way to derive a new record is
    ``dataclasses.replace``, which produces a new object and never mutates
    the source.
    """

    timestamp: datetime
    request_id: str
    memory_id: Optional[str]
    operation: KernelOperation
    principal_id: str
    result: AuditResult
    created_by: str
    modified_by: str
    modified_at: datetime
    operation_type: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Render the record as an JSON-safe dict (future SQLite adapter)."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "request_id": self.request_id,
            "memory_id": self.memory_id,
            "operation": self.operation.value,
            "principal_id": self.principal_id,
            "result": self.result.value,
            "created_by": self.created_by,
            "modified_by": self.modified_by,
            "modified_at": self.modified_at.isoformat(),
            "operation_type": self.operation_type,
            "details": dict(self.details),
        }


class AuditStore(Protocol):
    """Immutable, append-only audit persistence."""

    def append(self, record: AuditRecord) -> AuditRecord: ...

    def list(
        self,
        *,
        operation: Optional[KernelOperation] = None,
        memory_id: Optional[str] = None,
        principal_id: Optional[str] = None,
        result: Optional[AuditResult] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditRecord]: ...

    def count(self) -> int: ...


class InMemoryAuditStore:
    """Thread-safe, append-only in-memory audit store.

    Entries are never evicted or mutated, preserving audit immutability for
    the default (development) deployment.
    """

    def __init__(self) -> None:
        self._records: List[AuditRecord] = []
        self._lock = threading.Lock()

    def append(self, record: AuditRecord) -> AuditRecord:
        with self._lock:
            self._records.append(record)
        return record

    def list(
        self,
        *,
        operation: Optional[KernelOperation] = None,
        memory_id: Optional[str] = None,
        principal_id: Optional[str] = None,
        result: Optional[AuditResult] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditRecord]:
        with self._lock:
            records = [
                r
                for r in self._records
                if (operation is None or r.operation is operation)
                and (memory_id is None or r.memory_id == memory_id)
                and (principal_id is None or r.principal_id == principal_id)
                and (result is None or r.result is result)
            ]
        return records[offset : offset + limit]

    def count(self) -> int:
        with self._lock:
            return len(self._records)