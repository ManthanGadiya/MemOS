"""Canonical kernel operations for MemOS.

The Memory Kernel records every action under exactly one :class:`KernelOperation`.
This single enum feeds the audit log (:mod:`memos.kernel.audit`), the event bus
(:mod:`memos.kernel.events`), and the error mapper (:mod:`memos.kernel.errors`),
so no magic string ever crosses the kernel boundary.
"""

from __future__ import annotations

from enum import Enum


class KernelOperation(str, Enum):
    """The enumerated set of operations the Memory Kernel may perform.

    Values are lower-case, snake_case strings (mirroring the audit
    ``operation`` field from Security.md section 7 and SRS section 10.17).
    """

    CREATE = "create"
    READ = "read"
    LIST = "list"
    SEARCH = "search"
    UPDATE = "update"
    DELETE = "delete"
    ARCHIVE = "archive"
    RESTORE = "restore"
    TOUCH = "touch"
    REINDEX = "reindex"
    ADD_RELATIONSHIP = "add_relationship"
    REMOVE_RELATIONSHIP = "remove_relationship"
    GET_RELATIONSHIPS = "get_relationships"
    TRAVERSE = "traverse"
    ROLLBACK = "rollback"
    ADJUST_CONFIDENCE = "adjust_confidence"