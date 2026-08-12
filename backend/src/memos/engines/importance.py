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

3. **Confidence.** The confidence source from
   ``metadata['confidence_source']`` maps directly to the fixed base value
   documented in §4.3 — the value is used **verbatim, with no blending
   against a prior**. ``MANUAL_ASSIGNMENT`` takes the caller-provided
   ``metadata['confidence']`` value (clamped to [0, 1]) and raises
   :class:`~memos.domain.exceptions.ValidationError` when that value is
   missing or invalid. The resolved source label is recorded on the
   explanation.

Categories follow the documented 5-band scheme (§3.2), and every numeric
metadata input is sanitized so non-finite values (``NaN``, ``inf``) cannot
poison the deterministic formula or raise mid-computation.

Determinism: no random numbers, no mutable module state, no dependence on
storage or on a language model.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

from memos.config.settings import Settings
from memos.domain.exceptions import ValidationError
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
# Category bands (docs/Algorithms.md section 3.2)
# ---------------------------------------------------------------------------
#
# The documented 0..100 scale maps onto the raw score in [0, 1] via
# ``raw_score = importance / 100`` (see AL-003). Each constant below is the
# inclusive upper bound of a band on the raw scale:
#
#   raw score   | 0..100 scale | category
#   ------------+--------------+-------------
#   ≤ 0.20      | 0–20         | negligible
#   ≤ 0.40      | 21–40        | low
#   ≤ 0.60      | 41–60        | moderate
#   ≤ 0.80      | 61–80        | high
#   > 0.80      | 81–100       | critical

NEGLIGIBLE_BAND_UPPER: float = 0.20
"""Inclusive raw-score upper bound of the ``negligible`` band (0–20)."""

LOW_BAND_UPPER: float = 0.40
"""Inclusive raw-score upper bound of the ``low`` band (21–40)."""

MODERATE_BAND_UPPER: float = 0.60
"""Inclusive raw-score upper bound of the ``moderate`` band (41–60)."""

HIGH_BAND_UPPER: float = 0.80
"""Inclusive raw-score upper bound of the ``high`` band (61–80)."""

# ---------------------------------------------------------------------------
# Confidence model (docs/Algorithms.md section 4.3)
# ---------------------------------------------------------------------------

CONFIDENCE_SOURCE_VALUES: Dict[str, float] = {
    "SYSTEM_VERIFIED": 0.95,
    "USER_CONFIRMED": 0.90,
    "REPEATED_OBSERVATION": 0.80,
    "APPLICATION_PROVIDED": 0.70,
    "INFERRED": 0.50,
}
"""Fixed confidence base values per Algorithms.md section 4.3.

Values are used **directly** — there is deliberately no blending with a
prior. ``MANUAL_ASSIGNMENT`` is intentionally absent: its value is
caller-provided (``metadata['confidence']``), is clamped to [0, 1], and is
resolved separately, raising :class:`ValidationError` when missing or
invalid.
"""

CONFIDENCE_SOURCE_STORED_LABEL: str = "STORED"
"""Explanation label recorded when the stored confidence value was used
(i.e. no explicit confidence source resolved to the documented table)."""

# ---------------------------------------------------------------------------
# Explanation payload (docs/Algorithms.md section 3.6)
# ---------------------------------------------------------------------------

EXPLANATION_METHOD: str = "memos.importance.v1"
"""Explanation ``method`` identifier (Algorithms.md §3.6)."""

# ---------------------------------------------------------------------------
# Memory-type base weights (docs/Algorithms.md section 3.4)
# ---------------------------------------------------------------------------

TYPE_BASE_WEIGHTS: Dict[MemoryType, float] = {
    # Documented base weights (docs/Algorithms.md section 3.4).
    MemoryType.SEMANTIC: 60.0,
    MemoryType.EPISODIC: 40.0,
    MemoryType.WORKING: 20.0,
}

DEFAULT_TYPE_WEIGHT: float = 20.0
"""Type-weight fallback for any future MemoryType value (mirrors WORKING)."""

# Type priors used when deriving a relevance component from the memory itself.
TYPE_RELEVANCE_PRIORS: Dict[MemoryType, float] = {
    MemoryType.SEMANTIC: 0.7,
    MemoryType.EPISODIC: 0.5,
    MemoryType.WORKING: 0.4,
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


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Coerce ``value`` to a finite float, else return ``default``.

    Guards the deterministic formula against non-numeric or non-finite
    metadata values: ``float("nan")`` and ``float("inf")`` would otherwise
    slip through ``_clamp`` (NaN comparisons are always ``False``) and either
    poison the score or raise ``ValueError`` mid-computation.
    """
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _read_numeric_metadata(metadata: Dict[str, Any], keys: Sequence[str]) -> Optional[float]:
    """Return the first numeric value found under any of ``keys``.

    Accepts numbers, numeric strings, ``{"score": ...}`` dicts, and
    :class:`~memos.domain.memory.Confidence` objects. Returns ``None`` when
    no key holds a finite parseable number.
    """
    for key in keys:
        if key not in metadata:
            continue
        value = metadata[key]
        if isinstance(value, Confidence):
            return float(value.score)
        if isinstance(value, dict) and "score" in value:
            value = value["score"]
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
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
    important, else ``0.0``.

    Non-finite or non-numeric emphasis values are treated as absent.
    """
    for key in EXPLICIT_EMPHASIS_KEYS:
        if key not in memory.metadata:
            continue
        value = memory.metadata[key]
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        numeric = _safe_float(value)
        if numeric is None:
            continue
        return 1.0 if numeric else 0.0
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
        count = _safe_float(memory.access_count, 0.0)
    return int(_clamp(count, 0.0, float(RETRIEVAL_FREQUENCY_CAP)))


DECAY_CONSTANT: float = 0.0002
"""Decay coefficient in ``decay_factor = 1 / (1 + 0.0002 * age_hours)``
per Algorithms.md §10.3.
"""

def _compute_age_factor(memory: MemoryObject) -> float:
    """Return ``A``: the normalized age factor (recency for importance).

    Age is measured since the last access (an access "refreshes" the memory
    and triggers importance recalculation per section 3.7), or since
    creation when the memory has never been accessed.
    """
    reference = memory.last_accessed_at if memory.last_accessed_at is not None else memory.created_at
    reference = _coerce_aware_utc(reference)
    age_hours = max((now_utc() - reference).total_seconds() / 3600.0, 0.0)
    return 1.0 / (1.0 + IMPORTANCE_RECENCY_DECAY_PER_HOUR * age_hours)


def _compute_decay_metadata(memory: MemoryObject, base_importance: float) -> Dict[str, Any]:
    """Return decay metadata per Algorithms.md §10.2.

    Decay factor: ``1 / (1 + 0.0002 * age_hours)``
    Current importance: ``base_importance * decay_factor``
    """
    reference = memory.last_accessed_at if memory.last_accessed_at is not None else memory.created_at
    reference = _coerce_aware_utc(reference)
    age_hours = max((now_utc() - reference).total_seconds() / 3600.0, 0.0)
    decay_factor = 1.0 / (1.0 + DECAY_CONSTANT * age_hours)
    current_importance = base_importance * decay_factor
    return {
        "last_calculated": now_utc().isoformat(),
        "base_importance": round(base_importance, 4),
        "current_importance": round(current_importance, 4),
        "age_hours": round(age_hours, 4),
        "decay_factor": round(decay_factor, 6),
    }


def _compute_type_weight(memory: MemoryObject) -> float:
    """Return ``T``: the base weight for the memory's type."""
    return TYPE_BASE_WEIGHTS.get(memory.type, DEFAULT_TYPE_WEIGHT)


# ---------------------------------------------------------------------------
# Semantic component derivation (used when no SemanticScore is supplied)
# ---------------------------------------------------------------------------


def _derive_attention(memory: MemoryObject) -> float:
    """Derived attention: normalized content length.

    Longer content indicates a more substantial memory; episodic memories
    are naturally longer and thereby score higher.
    """
    length_factor = len(memory.content) / float(ATTENTION_SATURATION_LENGTH)
    return _clamp(length_factor, 0.0, 1.0)


def _derive_repetition(memory: MemoryObject) -> float:
    """Derived repetition: explicit metadata value, else normalized access
    count (re-observation strengthens a memory)."""
    explicit = _read_numeric_metadata(memory.metadata, REPETITION_KEYS)
    if explicit is not None:
        return _clamp(explicit, 0.0, 1.0)
    access_factor = _safe_float(memory.access_count, 0.0) / float(REPETITION_SATURATION_COUNT)
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


def _resolve_confidence_source(memory: MemoryObject) -> Tuple[float, str]:
    """Return ``(confidence, source_label)`` for ``memory``.

    Confidence values follow the fixed table in Algorithms.md §4.3 with **no
    blending against a prior**: a known source maps directly to its
    documented base value.

    Resolution order:

    1. ``metadata['confidence_source']``: a known source maps to its fixed
       base value; ``MANUAL_ASSIGNMENT`` requires a caller-provided
       ``metadata['confidence']`` (clamped to [0, 1]) and raises
       :class:`ValidationError` when that value is missing or invalid; an
       unknown label falls through to the stored confidence.
    2. ``metadata['confidence']`` when present.
    3. The stored :attr:`MemoryObject.confidence` field.

    :raises ValidationError: if ``confidence_source`` is ``MANUAL_ASSIGNMENT``
        and ``metadata['confidence']`` is absent or not a finite number.
    """
    raw_source = memory.metadata.get("confidence_source")
    if raw_source is not None:
        source_key = _normalize_confidence_source_key(raw_source)
        if source_key == "MANUAL_ASSIGNMENT":
            manual_value = _read_numeric_metadata(memory.metadata, CONFIDENCE_KEYS)
            if manual_value is None:
                raise ValidationError(
                    "confidence_source 'MANUAL_ASSIGNMENT' requires "
                    "metadata['confidence'] as a finite number in [0, 1]"
                )
            return _clamp(manual_value, 0.0, 1.0), source_key
        if source_key in CONFIDENCE_SOURCE_VALUES:
            return CONFIDENCE_SOURCE_VALUES[source_key], source_key
        # Unknown label: fall through to stored confidence.
    stored_value = _read_numeric_metadata(memory.metadata, CONFIDENCE_KEYS)
    if stored_value is not None:
        return _clamp(stored_value, 0.0, 1.0), CONFIDENCE_SOURCE_STORED_LABEL
    return _clamp(memory.confidence, 0.0, 1.0), CONFIDENCE_SOURCE_STORED_LABEL


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
        confidence. Always returns a valid :class:`ImportanceScore` whose
        ``components`` dict carries the documented explanation payload
        (``method``, ``last_calculated``) plus each contributing factor.
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
        confidence, confidence_source = _resolve_confidence_source(memory)

        decay_meta = _compute_decay_metadata(memory, importance)

        components: Dict[str, Any] = {
            "method": EXPLANATION_METHOD,
            "last_calculated": now_utc().isoformat(),
            "emphasis": emphasis,
            "type_weight": type_weight,
            "relationship_density": float(relationship_density),
            "retrieval_frequency": float(retrieval_frequency),
            "age_factor": round(age_factor, 6),
            "semantic_score": round(semantic.combined, 6),
            "confidence_source": confidence_source,
            "confidence": round(confidence, 6),
            "decay": decay_meta,
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

        Recalculation triggers (Algorithms.md §3.7): the caller invokes this
        method when a memory is created, retrieved (access refreshes
        ``last_accessed_at`` and feeds the recency factor), updated (new
        version), or when explicit recalculation is requested. Relationship
        add/remove events are covered through memory snapshots: this engine
        reads the relationship count from ``metadata`` (``relationship_count``
        or a ``relationships`` collection), so a snapshot taken after the
        graph change yields the updated score.
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
        """Map a raw score in [0, 1] to the documented 5-band category.

        Bands follow Algorithms.md §3.2 (0..100 scale; ``raw_score`` is the
        normalized score in [0, 1]). Each band upper bound is inclusive,
        matching the documented 0–20, 21–40, 41–60, 61–80, 81–100 ranges.

        ========== ==============
        raw score  category
        ========== ==============
        ≤ 0.20     ``negligible``
        ≤ 0.40     ``low``
        ≤ 0.60     ``moderate``
        ≤ 0.80     ``high``
        > 0.80     ``critical``
        ========== ==============
        """
        if raw_score <= NEGLIGIBLE_BAND_UPPER:
            return "negligible"
        if raw_score <= LOW_BAND_UPPER:
            return "low"
        if raw_score <= MODERATE_BAND_UPPER:
            return "moderate"
        if raw_score <= HIGH_BAND_UPPER:
            return "high"
        return "critical"
