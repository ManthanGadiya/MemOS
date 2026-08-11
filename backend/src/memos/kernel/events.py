"""In-memory event publishing for the Memory Kernel.

SystemArchitecture.md section 9 lists "event generation" as a kernel
responsibility. Version 1 ships an in-process, synchronous event bus with no
broker dependency: subscribers are plain callables, and events are published
**only after a transaction commits**. A rolled-back operation surfaces through
the audit log (``result=ROLLBACK``) and never through a success event.

A listener failure is caught and ignored so a post-commit subscriber can never
corrupt an already-committed operation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol

from memos.domain.memory import now_utc
from memos.kernel.operations import KernelOperation

Listener = Callable[["KernelEvent"], None]


@dataclass(frozen=True)
class KernelEvent:
    """An immutable, post-commit domain event published by the kernel."""

    kind: str
    request_id: str
    operation: KernelOperation
    memory_id: Optional[str]
    principal_id: str
    occurred_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)


def event_kind(operation: KernelOperation) -> str:
    """Map an operation to its conventional event kind (``memory.created``)."""
    return f"memory.{operation.value}"


class EventBus(Protocol):
    """Publish kernel events to zero or more listeners."""

    def subscribe(self, listener: Listener, kind: Optional[str] = None) -> None: ...

    def unsubscribe(self, listener: Listener) -> None: ...

    def publish(self, event: KernelEvent) -> None: ...


class InMemoryEventBus:
    """Thread-safe, synchronous, in-memory event bus.

    Listeners subscribed with a ``kind`` only receive events whose
    ``kind`` matches exactly; listeners subscribed without a kind receive
    every event. Listener exceptions are suppressed so they can never break
    the kernel's commit path.
    """

    def __init__(self) -> None:
        self._all: List[Listener] = []
        self._by_kind: Dict[str, List[Listener]] = {}
        self._lock = threading.Lock()

    def subscribe(self, listener: Listener, kind: Optional[str] = None) -> None:
        with self._lock:
            if kind is None:
                self._all.append(listener)
            else:
                self._by_kind.setdefault(kind, []).append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            self._all = [l for l in self._all if l is not listener]
            for listeners in self._by_kind.values():
                listeners[:] = [l for l in listeners if l is not listener]

    def publish(self, event: KernelEvent) -> None:
        with self._lock:
            listeners = list(self._all) + list(self._by_kind.get(event.kind, ()))
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - subscriber failure must not break commit
                pass