"""Typed relationships linking memory objects in the graph store."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from .memory import RelationshipType, now_utc


@dataclass
class Relationship:
    """A directed, typed edge between two memory objects.

    Semantics: ``source_id`` relates to ``target_id`` via ``type``.
    """

    source_id: str
    target_id: str
    type: RelationshipType = RelationshipType.RELATED_TO
    relationship_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=now_utc)

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["type"] = self.type.value
        d["created_at"] = self.created_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Relationship":
        cleaned = dict(data)
        cleaned["type"] = RelationshipType(cleaned["type"])
        return cls(**cleaned)