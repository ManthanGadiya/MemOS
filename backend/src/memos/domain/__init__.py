"""Domain package: core entities and validation rules for MemOS."""

from .exceptions import (
    ConfigurationError,
    EmbeddingError,
    ImmutabilityError,
    LifecycleTransitionError,
    MemOSError,
    NotFoundError,
    PermissionDeniedError,
    StorageError,
    TransactionError,
    ValidationError,
)
from .memory import (
    Confidence,
    ImportanceScore,
    LifecycleState,
    MemoryObject,
    MemoryType,
    PermissionLevel,
    RelationshipType,
    SemanticScore,
    now_utc,
)
from .relationship import Relationship

__all__ = [
    "ConfigurationError",
    "Confidence",
    "EmbeddingError",
    "ImmutabilityError",
    "ImportanceScore",
    "LifecycleState",
    "LifecycleTransitionError",
    "MemOSError",
    "MemoryObject",
    "MemoryType",
    "NotFoundError",
    "PermissionDeniedError",
    "PermissionLevel",
    "Relationship",
    "RelationshipType",
    "SemanticScore",
    "StorageError",
    "TransactionError",
    "ValidationError",
    "now_utc",
]