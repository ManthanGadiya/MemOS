"""Importance Engine for MemOS.

The Importance Engine computes the **long-term usefulness** of a Memory
Object for future reasoning, following the exact formula documented in
``docs/Algorithms.md`` section 3.5. It is a pure, deterministic,
storage-independent service: the same inputs always produce the same score,
and the score is fully explained by the returned ``components`` dict.

Documented formula (0..100 scale)
---------------------------------

    I = clamp(
            (E * 100)
          + (T * 0.35)
          + (min(R, 10) / 10 * 30)
          + (min(F, 10) / 10 * 10)
          + (A * 5),
            0,
            100
    )

with

- ``E``  explicit user emphasis, ``0`` or ``1``;
- ``T``  memory-type base weight (see ``TYPE_BASE_WEIGHTS``);
- ``R``  number of active relationships (capped at 10);
- ``F``  retrieval count (capped at 10);
- ``A``  normalized age factor: ``A = 1 / (1 + 0.0005 * age_hours)``.

This engine extends that documented formula in three ways, all of which are
mandated by the Importance Engine contract (see
``docs/SystemArchitecture.md`` section 16 and the ``ImportanceScore`` /
``SemanticScore`` domain objects):

1. **Semantic signal.** ``compute`` accepts an optional
   :class:`~memos.domain.memory.SemanticScore`. When provided, its
   ``combined`` value (0..1) contributes additively to the formula with a
   bounded budget of ``SEMANTIC_SIGNAL_MAX_POINTS`` (10 points on the 0..100
   scale, mirroring the retrieval-frequency budget). When omitted, the
   semantic dimensions are derived deterministically from the memory itself:
   attention from content length, repetition from metadata or
   ``access_count``, relevance from tags and type, and emotional intensity
   from metadata when present.

2. **Scale reconciliation.** ``Algorithms.md`` (AL-003) fixes importance on
   a 0..100 scale, and the retrieval ranking (§6.1) normalizes it via
   ``importance_n = score / 100``. ``ImportanceScore.raw_score`` is exactly
   that normalized value in [0, 1]; ``ImportanceScore.importance`` carries
   the 0..100 continuous score so the Retrieval Engine's formula works
   unchanged.

3. **Confidence.** The explicit confidence source from
   ``metadata['confidence_source']`` (values per §4.3) is blended with a
   base prior (``BASE_CONFIDENCE_PRIOR``) and clamped to [0, 1].

Determinism: no random numbers, no mutable module state, no dependence on
storage or on a language model.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

from memos.config.settings import Settings
from memos.domain.memory import (
    Confidence,
    ImportanceScore,
    MemoryObject,
    MemoryType,
    SemanticScore,
    now_utc,
)

# ---------------------------------------------------------------------------
# Documented formula constants (docs/Algorithms.md section 3.5)
# ---------------------------------------------------------------------------

IMPORTANCE_SCORE_MAX: float = 100.0
"""Upper bound of the documented importance scale (AL-003)."""

EXPLICIT_EMPHASIS_SCORE: float = 100.0
"""Contribution of explicit user emphasis (``E * 100``)."""

TYPE_WEIGHT_SCALE: float = 0.35
"""Scaling applied to the memory-type base weight (``T * 0.35``)."""

RELATIONSHIP_DENSITY_CAP: int = 10
"""Relationship count is capped before normalization (``min(R, 10)``)."""

RELATIONSHIP_DENSITY_WEIGHT: float = 30.0
"""Maximum points contributed by relationship density (``* 30``)."""

RETRIEVAL_FREQUENCY_CAP: int = 10
"""Retrieval count is capped before normalization (``min(F, 10)``)."""

RETRIEVAL_FREQUENCY_WEIGHT: float = 10.0
"""Maximum points contributed by retrieval frequency (``* 10``)."""

RECENCY_WEIGHT: float = 5.0
"""Maximum points contributed by the age factor (``A * 5``)."""

IMPORTANCE_RECENCY_DECAY_PER_HOUR: float = 0.0005
"""Decay coefficient in ``A = 1 / (1 + 0.0005 * age_hours)``.

The documented formula uses a reciprocal (not exponential) decay; the
documented constant is used verbatim per the "do not invent a different
formula" rule.
"""

# ---------------------------------------------------------------------------
# Semantic-signal extension (contract layer, not in Algorithms.md)
# ---------------------------------------------------------------------------

SEMANTIC_SIGNAL_MAX_POINTS: float = 10.0
"""Maximum 0..100 points the semantic score can add.

Chosen to mirror the retrieval-frequency budget (10 points) so that semantic
quality is a meaningful but secondary signal relative to emphasis,
relationship density, and type.
"""

ATTENTION_SATURATION_LENGTH: int = 500
"""Content length (characters) at which derived attention reaches 1.0."""

REPETITION_SATURATION_COUNT: int = 10
"""Access count at which derived repetition reaches 1.0."""

RELEVANCE_SATURATION_TAGS: int = 5
"""Tag count at which the tag component of derived relevance reaches 1.0."""

# ---------------------------------------------------------------------------
# Categorization thresholds (mapped onto the 0..1 raw score)
# ---------------------------------------------------------------------------

LOW_IMPORTANCE_THRESHOLD: float = 0.33
"""Raw scores strictly below this are categorized ``low``."""

HIGH_IMPORTANCE_THRESHOLD: float = 0.66
"""Raw scores strictly above this are categorized ``high``."""

# ---------------------------------------------------------------------------
# Confidence model (docs/Algorithms.md section 4.3)
# ---------------------------------------------------------------------------

BASE_CONFIDENCE_PRIOR: float = 0.5
"""Fallback confidence when no explicit source is present (the INFERRED
base value, and the :class:`MemoryObject` default)."""

CONFIDENCE_SOURCE_WEIGHT: float = 0.7
"""Weight of the explicit confidence source in the blend."""

CONFIDENCE_PRIOR_WEIGHT: float = 0.3
"""Weight of the base prior in the blend (sums with the source weight to 1)."""

CONFIDENCE_SOURCE_VALUES: Dict[str, float] = {
    "SYSTEM_VERIFIED": 0.95,
    "USER_CONFIRMED": 0.90,
    "REPEATED_OBSERVATION": 0.80,
    "APPLICATION_PROVIDED": 0.70,
    "INFERRED": 0.50,
}
"""Fixed confidence base values per Algorithms.md section 4.3.

``MANUAL_ASSIGNMENT`` is intentionally absent: its value is caller-provided
(``metadata['confidence']``) and is resolved separately.
"""

# ---------------------------------------------------------------------------
# Memory-type base weights (docs/Algorithms.md section 3.4, extended)
# ---------------------------------------------------------------------------

TYPE_BASE_WEIGHTS: Dict[MemoryType, float] = {
    # Documented weights.
    MemoryType.SEMANTIC: 60.0,
    MemoryType.EPISODIC: 40.0,
    # Extension for the remaining MemoryType values (assumptions, see report):
    # - FACT: long-term factual knowledge, semantically equivalent to SEMANTIC.
    # - PROCEDURAL: durable know-how, slightly below pure semantic facts.
    # - RELATIONSHIP / PREFERENCE: stable structural signals for future reasoning.
    # - GENERAL: catch-all scratch memory, mirrors documented WORKING = 20.
    MemoryType.FACT: 60.0,
    MemoryType.PROCEDURAL: 50.0,
    MemoryType.RELATIONSHIP: 45.0,
    MemoryType.PREFERENCE: 45.0,
    MemoryType.GENERAL: 20.0,
}

DEFAULT_TYPE_WEIGHT: float = 20.0
"""Type-weight fallback for any future MemoryType value."""

# Type priors used when deriving a relevance component from the memory itself.
TYPE_RELEVANCE_PRIORS: Dict[MemoryType, float] = {
    MemoryType.PREFERENCE: 0.9,
    MemoryType.RELATIONSHIP: 0.8,
    MemoryType.SEMANTIC: 0.7,
    MemoryType.FACT: 0.7,
    MemoryType.PROCEDURAL: 0.6,
    MemoryType.EPISODIC: 0.5,
    MemoryType.GENERAL: 0.4,
}

DEFAULT_TYPE_RELEVANCE: float = 0.4
"""Relevance prior fallback for any future MemoryType value."""

# Metadata keys consulted for each factor (memory objects carry no explicit
# relationship/retrieval/emphasis fields, so the engine reads them from the
# free-form ``metadata`` dict, falling back to first-class fields).
EXPLICIT_EMPHASIS_KEYS: Tuple[str, ...] = ("emphasis", "emphasized", "important")
RELATIONSHIP_COUNT_KEYS: Tuple[str, ...] = (
    "relationship_count",
    "active_relationships",
    "relationship_density",
)
RETRIEVAL_COUNT_KEYS: Tuple[str, ...] = ("retrieval_count", "retrieval_frequency")
CONFIDENCE_KEYS: Tuple[str, ...] = ("confidence",)
REPETITION_KEYS: Tuple[str, ...] = ("repetition",)
EMOTIONAL_INTENSITY_KEYS: Tuple[str, ...] = ("emotional_intensity",)


# ---------------------------------------------------------------------------
# Pure numeric helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lower: float, upper: float) -> float:
    """Bound ``value`` to the inclusive interval ``[lower, upper]``."""
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def _coerce_aware_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime (naive inputs assumed UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _read_numeric_metadata(metadata: Dict[str, Any], keys: Sequence[str]) -> Optional[float]:
    """Return the first numeric value found under any of ``keys``.

    Accepts numbers, numeric strings, ``{"score": ...}`` dicts, and
    :class:`~memos.domain.memory.Confidence` objects. Returns ``None`` when
    no key holds a parseable number.
    """
    for key in keys:
        if key not in metadata:
            continue
        value = metadata[key]
        if isinstance(value, Confidence):
            return float(value.score)
        if isinstance(value, dict) and "score" in value:
            value = value["score"]
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_confidence_source_key(raw: object) -> str:
    """Normalize a confidence source label for table lookup.

    Accepts ``"system_verified"``, ``"SYSTEM VERIFIED"``, etc.
    """
    return str(raw).strip().upper().replace(" ", "_")


# ---------------------------------------------------------------------------
# Factor resolvers (Algorithms.md sections 3.3 / 3.5)
# ---------------------------------------------------------------------------


def _resolve_explicit_emphasis(memory: MemoryObject) -> float:
    """Return ``E``: ``1.0`` when the owner explicitly marked the memory
    important, else ``0.0``."""
    for key in EXPLICIT_EMPHASIS_KEYS:
        if key not in memory.metadata:
            continue
        value = memory.metadata[key]
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        try:
            return 1.0 if float(value) else 0.0
        except (TypeError, ValueError):
            continue
    return 0.0


def _resolve_relationship_density(memory: MemoryObject) -> int:
    """Return ``R``: the number of active relationships, capped at 10.

    Relationship topology lives in the Graph Engine, so the count is read
    from metadata (or a ``relationships`` collection) rather than from the
    Memory Object itself.
    """
    count = _read_numeric_metadata(memory.metadata, RELATIONSHIP_COUNT_KEYS)
    if count is None:
        raw_relationships = memory.metadata.get("relationships")
        if isinstance(raw_relationships, (list, tuple, set, dict)):
            count = float(len(raw_relationships))
    if count is None:
        return 0
    return int(_clamp(count, 0.0, float(RELATIONSHIP_DENSITY_CAP)))


def _resolve_retrieval_frequency(memory: MemoryObject) -> int:
    """Return ``F``: the retrieval count, capped at 10.

    Prefers explicit retrieval metadata, falling back to the first-class
    ``access_count`` field.
    """
    count = _read_numeric_metadata(memory.metadata, RETRIEVAL_COUNT_KEYS)
    if count is None:
        count = float(memory.access_count)
    return int(_clamp(count, 0.0, float(RETRIEVAL_FREQUENCY_CAP)))


def _compute_age_factor(memory: MemoryObject) -> float:
    """Return ``A``: the normalized age factor.

    Age is measured since the last access (an access "refreshes" the memory
    and triggers importance recalculation per section 3.7), or since
    creation when the memory has never been accessed.
    """
    reference = memory.last_accessed_at if memory.last_accessed_at is not None else memory.created_at
    reference = _coerce_aware_utc(reference)
    age_hours = max((now_utc() - reference).total_seconds() / 3600.0, 0.0)
    return 1.0 / (1.0 + IMPORTANCE_RECENCY_DECAY_PER_HOUR * age_hours)


def _compute_type_weight(memory: MemoryObject) -> float:
    """Return ``T``: the base weight for the memory's type."""
    return TYPE_BASE_WEIGHTS.get(memory.type, DEFAULT_TYPE_WEIGHT)


# ---------------------------------------------------------------------------
# Semantic component derivation (used when no SemanticScore is supplied)
# ---------------------------------------------------------------------------


def _derive_attention(memory: MemoryObject) -> float:
    """Derived attention: normalized content length.

    Longer content indicates a more substantial memory; episodic and
    procedural memories are naturally longer and thereby score higher.
    """
    length_factor = len(memory.content) / float(ATTENTION_SATURATION_LENGTH)
    return _clamp(length_factor, 0.0, 1.0)


def _derive_repetition(memory: MemoryObject) -> float:
    """Derived repetition: explicit metadata value, else normalized access
    count (re-observation strengthens a memory)."""
    explicit = _read_numeric_metadata(memory.metadata, REPETITION_KEYS)
    if explicit is not None:
        return _clamp(explicit, 0.0, 1.0)
    access_factor = memory.access_count / float(REPETITION_SATURATION_COUNT)
    return _clamp(access_factor, 0.0, 1.0)


def _derive_relevance(memory: MemoryObject) -> float:
    """Derived relevance: blend of tag coverage and a type-based prior."""
    tag_factor = _clamp(len(memory.tags) / float(RELEVANCE_SATURATION_TAGS), 0.0, 1.0)
    type_prior = TYPE_RELEVANCE_PRIORS.get(memory.type, DEFAULT_TYPE_RELEVANCE)
    return _clamp(0.5 * tag_factor + 0.5 * type_prior, 0.0, 1.0)


def _derive_emotional_intensity(memory: MemoryObject) -> float:
    """Derived emotional intensity: read from metadata when present.

    A 0..1 value is used directly; a 0..10 scale is tolerated and normalized.
    Absent metadata contributes zero intensity.
    """
    raw = _read_numeric_metadata(memory.metadata, EMOTIONAL_INTENSITY_KEYS)
    if raw is None:
        return 0.0
    if raw > 1.0:
        raw = raw / 10.0
    return _clamp(raw, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Confidence resolution (Algorithms.md section 4.3)
# ---------------------------------------------------------------------------


def _resolve_confidence_source(memory: MemoryObject) -> float:
    """Return the explicit confidence value (0..1) for ``memory``.

    Resolution order:

    1. ``metadata['confidence_source']``: a known source maps to its fixed
       base value; ``MANUAL_ASSIGNMENT`` uses the caller-provided
       ``metadata['confidence']`` (falling back to the base prior); an
       unknown label falls back to the stored confidence.
    2. ``metadata['confidence']`` when present.
    3. The stored :attr:`MemoryObject.confidence` field.
    """
    raw_source = memory.metadata.get("confidence_source")
    if raw_source is not None:
        source_key = _normalize_confidence_source_key(raw_source)
        if source_key == "MANUAL_ASSIGNMENT":
            manual_value = _read_numeric_metadata(memory.metadata, CONFIDENCE_KEYS)
            if manual_value is not None:
                return _clamp(manual_value, 0.0, 1.0)
            return BASE_CONFIDENCE_PRIOR
        if source_key in CONFIDENCE_SOURCE_VALUES:
            return CONFIDENCE_SOURCE_VALUES[source_key]
        # Unknown label: fall through to stored confidence.
    stored_value = _read_numeric_metadata(memory.metadata, CONFIDENCE_KEYS)
    if stored_value is not None:
        return _clamp(stored_value, 0.0, 1.0)
    return _clamp(memory.confidence, 0.0, 1.0)


def _combine_confidence(source_value: float) -> float:
    """Blend an explicit confidence source with the base prior and clamp."""
    blended = (
        CONFIDENCE_SOURCE_WEIGHT * _clamp(source_value, 0.0, 1.0)
        + CONFIDENCE_PRIOR_WEIGHT * BASE_CONFIDENCE_PRIOR
    )
    return _clamp(blended, 0.0, 1.0)


class ImportanceEngine:
    """Computes the long-term importance of Memory Objects.

    The engine depends only on an immutable :class:`Settings` object and
    holds no runtime state, keeping it deterministic and trivially testable.
    It owns importance computation and score explanation only; confidence,
    retrieval, and lifecycle are owned by other services.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # ``importance_epochs`` is reserved for the Version 2 scheduled
        # decay worker; the Version 1 formula is epoch-free.
        self._importance_epochs: int = settings.importance_epochs

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------
    def compute(
        self,
        memory: MemoryObject,
        semantic_score: Optional[SemanticScore] = None,
    ) -> ImportanceScore:
        """Compute importance for a Memory Object.

        Combines the documented factors (emphasis, type, relationship
        density, retrieval frequency, age) with the semantic signal and
        confidence. Always returns a valid :class:`ImportanceScore`.
        """
        semantic = (
            semantic_score if semantic_score is not None else self._derive_semantic_score(memory)
        )
        semantic_points = _clamp(semantic.combined, 0.0, 1.0) * SEMANTIC_SIGNAL_MAX_POINTS

        emphasis = _resolve_explicit_emphasis(memory)
        type_weight = _compute_type_weight(memory)
        relationship_density = _resolve_relationship_density(memory)
        retrieval_frequency = _resolve_retrieval_frequency(memory)
        age_factor = _compute_age_factor(memory)

        document_score = (
            emphasis * EXPLICIT_EMPHASIS_SCORE
            + type_weight * TYPE_WEIGHT_SCALE
            + (relationship_density / float(RELATIONSHIP_DENSITY_CAP))
            * RELATIONSHIP_DENSITY_WEIGHT
            + (retrieval_frequency / float(RETRIEVAL_FREQUENCY_CAP))
            * RETRIEVAL_FREQUENCY_WEIGHT
            + age_factor * RECENCY_WEIGHT
            + semantic_points
        )
        importance = _clamp(document_score, 0.0, IMPORTANCE_SCORE_MAX)
        raw_score = importance / IMPORTANCE_SCORE_MAX
        confidence = _combine_confidence(_resolve_confidence_source(memory))

        components: Dict[str, float] = {
            "emphasis": emphasis,
            "type_weight": type_weight,
            "relationship_density": float(relationship_density),
            "retrieval_frequency": float(retrieval_frequency),
            "age_factor": round(age_factor, 6),
            "semantic_score": round(semantic.combined, 6),
            "confidence": round(confidence, 6),
        }

        return ImportanceScore(
            raw_score=raw_score,
            importance=importance,
            category=self._categorize(raw_score),
            confidence=confidence,
            components=components,
        )

    def update_memory(
        self,
        memory: MemoryObject,
        semantic_score: Optional[SemanticScore] = None,
    ) -> MemoryObject:
        """Return a NEW Memory Object with importance fields populated.

        The input ``memory`` is never mutated; identity, content, lifecycle,
        and version fields are carried over unchanged.
        """
        score = self.compute(memory, semantic_score)
        return replace(
            memory,
            importance=score.importance,
            importance_category=score.category,
            confidence=score.confidence,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _derive_semantic_score(memory: MemoryObject) -> SemanticScore:
        """Build a deterministic SemanticScore from the memory itself."""
        return SemanticScore(
            attention=_derive_attention(memory),
            repetition=_derive_repetition(memory),
            relevance=_derive_relevance(memory),
            emotional_intensity=_derive_emotional_intensity(memory),
        )

    @staticmethod
    def _categorize(raw_score: float) -> str:
        """Map a raw score in [0, 1] to ``low`` | ``medium`` | ``high``."""
        if raw_score < LOW_IMPORTANCE_THRESHOLD:
            return "low"
        if raw_score > HIGH_IMPORTANCE_THRESHOLD:
            return "high"
        return "medium"
