"""The Memory Kernel — the single authority for all MemOS operations.

SystemArchitecture.md section 9: the kernel is the central gateway that every
request enters. It validates requests, enforces permissions, owns all
transactions, coordinates the engines, writes audit records, and publishes
events. It contains no business-specific memory algorithms — those live in the
injected engines.

Every write follows the documented flow::

    validate -> permission check -> begin transaction -> snapshot before
    -> engine service -> commit -> audit(SUCCESS
    -> publish event

On failure: the transaction rolls back its before-images (metadata -> graph ->
version -> vector, per section 33.5), an audit record is written with
``result=ROLLBACK`` (``DENIED`` for a pre-authorization rejection), and a
structured :class:`KernelError` is raised.

Reads route through the kernel and the engines' permission filters; they never
open a transaction and never mutate data.
"""

from __future__ import annotations

import functools
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from memos.config.settings import Settings
from memos.domain.exceptions import MemOSError, NotFoundError, PermissionDeniedError
from memos.domain.memory import (
    LifecycleState,
    MemoryObject,
    MemoryType,
    PermissionLevel,
    now_utc,
)
from memos.domain.relationship import Relationship, RelationshipType
from memos.engines.graph import GraphEngine
from memos.engines.importance import ImportanceEngine
from memos.engines.memory import MemoryEngine
from memos.engines.permission import SYSTEM_PRINCIPAL, PermissionEngine
from memos.engines.retrieval import RetrievalEngine, ScoredMemory
from memos.engines.version import MemoryVersion, VersionEngine
from memos.kernel.audit import AuditRecord, AuditResult, AuditStore
from memos.kernel.errors import KernelError, KernelErrorCode, to_kernel_error
from memos.kernel.events import EventBus, KernelEvent, event_kind
from memos.kernel.operations import KernelOperation
from memos.kernel.transaction import Transaction
from memos.kernel.validation import RequestValidator
from memos.storage.protocols import GraphStore, MetadataStore, VectorStore


class MemoryKernel:
    """Coordinates all MemOS subsystems through a single validated gateway.

    Every dependency is injected (no global state). The kernel re-exposes the
    engine surface as its own public API so the future REST/MCP layers never
    import engines directly.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        memory_engine: MemoryEngine,
        version_engine: VersionEngine,
        importance_engine: ImportanceEngine,
        graph_engine: GraphEngine,
        permission_engine: PermissionEngine,
        retrieval_engine: RetrievalEngine,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
        graph_store: GraphStore,
        audit_store: AuditStore,
        event_bus: EventBus,
        validator: Optional[RequestValidator] = None,
    ) -> None:
        self._settings = settings
        self._memory_engine = memory_engine
        self._version_engine = version_engine
        self._importance_engine = importance_engine
        self._graph_engine = graph_engine
        self._permission_engine = permission_engine
        self._retrieval_engine = retrieval_engine
        self._metadata_store = metadata_store
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._audit_store = audit_store
        self._event_bus = event_bus
        self._validator = validator or RequestValidator(settings)

    # ==================================================================
    # Private coordination helpers
    # ==================================================================
    @staticmethod
    def _new_request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _structured_errors(method: Callable[..., Any]) -> Callable[..., Any]:
        """Ensure every public gateway call raises a structured KernelError.

        Pre-transaction validation and any error raised outside the write/read
        paths must still surface as KernelError (Security.md section 10: the
        three codes are the only client-visible failure channels). Known
        MemOSError subclasses are mapped by :func:`to_kernel_error`; errors
        already structured pass through untouched.
        """

        @functools.wraps(method)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return method(*args, **kwargs)
            except KernelError:
                raise
            except MemOSError as error:
                raise to_kernel_error(error) from error

        return wrapper

    def _audit(
        self,
        operation: KernelOperation,
        request_id: str,
        principal_id: str,
        memory_id: Optional[str],
        result: AuditResult,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        record = AuditRecord(
            timestamp=now_utc(),
            request_id=request_id,
            memory_id=memory_id,
            operation=operation,
            principal_id=principal_id,
            result=result,
            created_by=principal_id,
            modified_by=principal_id,
            modified_at=now_utc(),
            operation_type=operation.value.upper(),
            details=dict(details or {}),
        )
        self._audit_store.append(record)

    def _publish(
        self,
        operation: KernelOperation,
        request_id: str,
        principal_id: str,
        memory_id: Optional[str],
        payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._event_bus.publish(
            KernelEvent(
                kind=event_kind(operation),
                request_id=request_id,
                operation=operation,
                memory_id=memory_id,
                principal_id=principal_id,
                occurred_at=now_utc(),
                payload=dict(payload or {}),
            )
        )

    def _transaction(
        self, operation: KernelOperation, request_id: str, principal_id: str
    ) -> Transaction:
        return Transaction(
            metadata_store=self._metadata_store,
            vector_store=self._vector_store,
            graph_store=self._graph_store,
            read_versions=self._version_engine.list_versions,
            truncate_versions=self._version_engine.truncate_to,
            request_id=request_id,
            operation=operation,
            principal_id=principal_id,
        )

    def _write(
        self,
        operation: KernelOperation,
        request_id: str,
        principal_id: str,
        memory_id: Optional[str],
        write_fn: Callable[[Transaction], Any],
    ) -> Any:
        """Run ``write_fn`` atomically and audit/publish the outcome.

        A before-image snapshot is captured for ``memory_id`` (when known)
        *before* the write; on failure the transaction rolls back those images
        and an ``ROLLBACK`` audit record is written before the structured
        kernel error is raised. On success the transaction commits and a
        ``SUCCESS`` audit record plus a post-commit event are emitted.
        """
        transaction = self._transaction(operation, request_id, principal_id)
        transaction.begin()
        if memory_id is not None:
            transaction.snapshot_memory(memory_id)

        try:
            result = write_fn(transaction)
        except Exception as error:  # noqa: BLE001 - kernel boundary catches all
            if transaction.is_active():
                try:
                    transaction.rollback()
                except Exception:  # noqa: BLE001 - never mask the original error
                    pass
            self._audit(
                operation,
                request_id,
                principal_id,
                memory_id,
                AuditResult.ROLLBACK,
                {"error_code": _error_code_name(error)},
            )
            raise to_kernel_error(error, request_id=request_id) from error

        transaction.commit()
        self._audit(
            operation,
            request_id,
            principal_id,
            memory_id,
            AuditResult.SUCCESS,
            {"version": getattr(result, "version", None)},
        )
        self._publish(operation, request_id, principal_id, memory_id)
        return result

    def _read(
        self,
        operation: KernelOperation,
        request_id: str,
        principal_id: str,
        memory_id: Optional[str],
        read_fn: Callable[[], Any],
    ) -> Any:
        """Run a read; permission failures are audited as ``DENIED``."""
        try:
            return read_fn()
        except PermissionDeniedError as error:
            self._audit(
                operation,
                request_id,
                principal_id,
                memory_id,
                AuditResult.DENIED,
                {"error_code": "PERMISSION_DENIED"},
            )
            raise to_kernel_error(error, request_id=request_id) from error
        except MemOSError as error:
            raise to_kernel_error(error, request_id=request_id) from error

    def _require_modify_target(
        self,
        memory_id: str,
        principal_id: str,
        *,
        operation: KernelOperation,
        request_id: str,
    ) -> None:
        """Fetch the target and authorize modification before any write.

        Runs *before* the transaction opens, so a denied request never starts
        work (Security.md section 10: permission validation before execution)
        and is audited as ``DENIED``.
        """
        memory = self._metadata_store.get(memory_id)
        if memory is None:
            raise KernelError(
                KernelErrorCode.INVALID_REQUEST,
                f"memory {memory_id!r} not found",
                {"request_id": request_id},
            )
        try:
            self._permission_engine.require_modify(memory, principal_id)
        except PermissionDeniedError as error:
            self._audit(
                operation,
                request_id,
                principal_id,
                memory_id,
                AuditResult.DENIED,
            )
            raise to_kernel_error(error, request_id=request_id) from error

    def _require_read_access(
        self,
        memory_id: str,
        principal_id: str,
        request_id: str,
    ) -> None:
        """Fetch the target and authorize read access.

        Used by read-only version endpoints so a caller who may not read a
        memory cannot read its history. Permission failures are audited as
        ``DENIED`` by :meth:`_read`.
        """
        memory = self._metadata_store.get(memory_id)
        if memory is None:
            raise KernelError(
                KernelErrorCode.INVALID_REQUEST,
                f"memory {memory_id!r} not found",
                {"request_id": request_id},
            )
        self._permission_engine.require_access(memory, principal_id)

    # ==================================================================
    # Create
    # ==================================================================
    @_structured_errors
    def create(
        self,
        content: str,
        owner_id: str = "default",
        memory_type: MemoryType = MemoryType.SEMANTIC,
        namespace: str = "personal",
        title: str = "",
        source: str = "",
        summary: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        permission: Optional[PermissionLevel] = None,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> MemoryObject:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        self._validator.validate_create(content, owner_id, memory_type, permission, tags, metadata)
        resolved_permission = self._validator.resolve_permission(permission)

        # Allocate identity up front so the transaction can capture a
        # before-image and roll back even a partially-created memory, and so
        # the audit record carries the Memory ID (Security.md section 7).
        memory_id = str(uuid.uuid4())

        def create_fn(transaction: Transaction) -> MemoryObject:
            return self._memory_engine.create(
                content=content,
                owner_id=owner_id,
                memory_type=memory_type,
                namespace=namespace,
                title=title,
                source=source,
                summary=summary,
                tags=tags,
                metadata=metadata,
                permission=resolved_permission,
                memory_id=memory_id,
            )

        return self._write(
            KernelOperation.CREATE,
            request_id,
            principal_id,
            memory_id,
            create_fn,
        )

    # ==================================================================
    # Reads
    # ==================================================================
    @_structured_errors
    def get(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> MemoryObject:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)
        return self._read(
            KernelOperation.READ,
            request_id,
            principal_id,
            memory_id,
            lambda: self._forbid_deleted_read(
                self._memory_engine.get(memory_id, principal_id=principal_id)
            ),
        )

    @staticmethod
    def _forbid_deleted_read(memory: MemoryObject) -> MemoryObject:
        """Reject reads of logically-deleted memories (SRS 11.4: DELETED is
        terminal; a deleted memory is not addressable)."""
        if memory.state is LifecycleState.DELETED:
            raise NotFoundError(f"memory {memory.memory_id!r} is deleted")
        return memory

    @_structured_errors
    def list_memories(
        self,
        owner_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        state: Optional[LifecycleState] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> List[MemoryObject]:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        return self._read(
            KernelOperation.LIST,
            request_id,
            principal_id,
            None,
            lambda: self._memory_engine.list_memories(
                owner_id=owner_id,
                memory_type=memory_type,
                state=state,
                tags=tags,
                limit=limit,
                offset=offset,
                principal_id=principal_id,
            ),
        )

    @_structured_errors
    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        owner_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        state: Optional[LifecycleState] = None,
        tags: Optional[List[str]] = None,
        principal_id: str = SYSTEM_PRINCIPAL,
        graph_expansion: bool = False,
        request_id: Optional[str] = None,
    ) -> List[ScoredMemory]:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        self._validator.validate_search(query, top_k, tags)
        return self._read(
            KernelOperation.SEARCH,
            request_id,
            principal_id,
            None,
            lambda: self._retrieval_engine.hybrid_search(
                query=query,
                top_k=top_k,
                owner_id=owner_id,
                memory_type=memory_type,
                state=state,
                tags=tags,
                principal_id=principal_id,
                graph_expansion=graph_expansion,
            ),
        )

    # ==================================================================
    # Mutations
    # ==================================================================
    @_structured_errors
    def update(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
        **fields: Any,
    ) -> MemoryObject:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)
        self._validator.validate_update(memory_id, fields)
        self._require_modify_target(
            memory_id, principal_id, operation=KernelOperation.UPDATE, request_id=request_id
        )
        return self._write(
            KernelOperation.UPDATE,
            request_id,
            principal_id,
            memory_id,
            lambda txn: self._memory_engine.update(memory_id, principal_id=principal_id, **fields),
        )

    @_structured_errors
    def archive(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> MemoryObject:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)
        self._require_modify_target(
            memory_id, principal_id, operation=KernelOperation.ARCHIVE, request_id=request_id
        )
        return self._write(
            KernelOperation.ARCHIVE,
            request_id,
            principal_id,
            memory_id,
            lambda txn: self._memory_engine.archive(memory_id, principal_id=principal_id),
        )

    @_structured_errors
    def restore(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> MemoryObject:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)
        self._require_modify_target(
            memory_id, principal_id, operation=KernelOperation.RESTORE, request_id=request_id
        )
        return self._write(
            KernelOperation.RESTORE,
            request_id,
            principal_id,
            memory_id,
            lambda txn: self._memory_engine.restore(memory_id, principal_id=principal_id),
        )

    @_structured_errors
    def delete(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> None:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)
        self._require_modify_target(
            memory_id, principal_id, operation=KernelOperation.DELETE, request_id=request_id
        )
        return self._write(
            KernelOperation.DELETE,
            request_id,
            principal_id,
            memory_id,
            lambda txn: self._memory_engine.delete(memory_id, principal_id=principal_id),
        )

    @_structured_errors
    def touch(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> MemoryObject:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)
        self._require_modify_target(
            memory_id, principal_id, operation=KernelOperation.TOUCH, request_id=request_id
        )
        return self._write(
            KernelOperation.TOUCH,
            request_id,
            principal_id,
            memory_id,
            lambda txn: self._memory_engine.get(memory_id, principal_id=principal_id),
        )

    @_structured_errors
    def reindex(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> MemoryObject:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)
        self._require_modify_target(
            memory_id, principal_id, operation=KernelOperation.REINDEX, request_id=request_id
        )
        return self._write(
            KernelOperation.REINDEX,
            request_id,
            principal_id,
            memory_id,
            lambda txn: self._memory_engine.reindex(memory_id, principal_id=principal_id),
        )

    # ==================================================================
    # Relationships
    # ==================================================================
    @_structured_errors
    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: RelationshipType,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> Relationship:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        self._validator.validate_relationship(source_id, target_id, weight)
        if not isinstance(relationship_type, RelationshipType):
            raise KernelError(
                KernelErrorCode.INVALID_REQUEST,
                f"invalid relationship type: {relationship_type!r}",
                {"request_id": request_id},
            )
        return self._write(
            KernelOperation.ADD_RELATIONSHIP,
            request_id,
            principal_id,
            source_id,
            lambda txn: self._graph_engine.add_relationship(
                source_id=source_id,
                target_id=target_id,
                relationship_type=relationship_type,
                weight=weight,
                metadata=metadata,
            ),
        )

    @_structured_errors
    def remove_relationship(
        self,
        relationship_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> None:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        if not isinstance(relationship_id, str) or not relationship_id.strip():
            raise KernelError(
                KernelErrorCode.INVALID_REQUEST,
                "relationship_id must be a non-empty string",
                {"request_id": request_id},
            )
        before = self._find_relationship(relationship_id)

        def _remove_fn(transaction: Transaction) -> None:
            if before is not None:
                transaction.stage_undo(
                    "restore_relationship",
                    lambda: self._graph_store.upsert_relationship(before),
                )
            self._graph_engine.remove_relationship(relationship_id)

        return self._write(
            KernelOperation.REMOVE_RELATIONSHIP,
            request_id,
            principal_id,
            before.source_id if before is not None else None,
            _remove_fn,
        )

    @_structured_errors
    def get_relationships(
        self,
        memory_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
        direction: str = "any",
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> List[Relationship]:
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        return self._graph_engine.get_relationships(
            memory_id=memory_id,
            relationship_type=relationship_type,
            direction=direction,
        )

    # ==================================================================
    # Versions
    # ==================================================================
    @_structured_errors
    def list_versions(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> List[MemoryVersion]:
        """Return the full version history for ``memory_id`` (oldest first).

        Access is governed by a READ permission check on the current object:
        a caller who may not read the memory may not read its history.
        """
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)

        def read_versions() -> List[MemoryVersion]:
            self._require_read_access(memory_id, principal_id, request_id)
            return self._version_engine.list_versions(memory_id)

        return self._read(
            KernelOperation.READ,
            request_id,
            principal_id,
            memory_id,
            read_versions,
        )

    @_structured_errors
    def get_version(
        self,
        memory_id: str,
        version: int,
        principal_id: str = SYSTEM_PRINCIPAL,
        request_id: Optional[str] = None,
    ) -> MemoryVersion:
        """Return the snapshot for ``memory_id`` at ``version``.

        Access is governed by a READ permission check on the current object,
        matching :meth:`list_versions`.
        """
        request_id = request_id or self._new_request_id()
        self._validator.validate_principal(principal_id)
        memory_id = self._validator.validate_memory_id(memory_id)

        def read_version() -> MemoryVersion:
            self._require_read_access(memory_id, principal_id, request_id)
            return self._version_engine.get_version(memory_id, version)

        return self._read(
            KernelOperation.READ,
            request_id,
            principal_id,
            memory_id,
            read_version,
        )

    # ==================================================================
    # System introspection (read-only, no per-principal data)
    # ==================================================================
    @property
    def settings(self) -> Settings:
        """Return the runtime configuration (read-only accessor)."""
        return self._settings

    def statistics(self) -> Dict[str, Any]:
        """Return aggregate counts useful for a dashboard.

        Only store-level aggregates are exposed; no memory content or
        per-principal data leaves the kernel.
        """
        return {
            "memory_count": self._metadata_store.count(),
            "relationship_count": len(self._graph_store.get_relationships(
                memory_id=None, relationship_type=None, direction="any"
            )),
            "audit_count": self._audit_store.count(),
        }

    def health(self) -> Dict[str, str]:
        """Return machine-readable liveness of the kernel and its stores."""
        statuses: Dict[str, str] = {"kernel": "ok"}
        try:
            self._metadata_store.count()
            statuses["metadata_store"] = "ok"
        except Exception:  # noqa: BLE001 - liveness probe must not raise
            statuses["metadata_store"] = "unavailable"
        return statuses

    # ==================================================================
    # Lifecycle / audit utilities
    # ==================================================================
    def list_audit(
        self,
        *,
        operation: Optional[KernelOperation] = None,
        memory_id: Optional[str] = None,
        principal_id: Optional[str] = None,
        result: Optional[AuditResult] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditRecord]:
        return self._audit_store.list(
            operation=operation,
            memory_id=memory_id,
            principal_id=principal_id,
            result=result,
            limit=limit,
            offset=offset,
        )

    def close(self) -> None:
        self._metadata_store.close()
        self._vector_store.close()
        self._graph_store.close()

    # ------------------------------------------------------------------
    # Small private helpers
    # ------------------------------------------------------------------
    def _find_relationship(self, relationship_id: str) -> Optional[Relationship]:
        for relationship in self._graph_store.get_relationships(
            memory_id=None, relationship_type=None, direction="any"
        ):
            if relationship.relationship_id == relationship_id:
                return relationship
        return None


def _error_code_name(error: Exception) -> str:
    if isinstance(error, KernelError):
        return error.code.value
    if isinstance(error, MemOSError):
        return str(getattr(error, "code", "memos_error"))
    return "INTERNAL_ERROR"
