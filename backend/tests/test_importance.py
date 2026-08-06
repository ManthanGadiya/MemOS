"""Unit tests for the MemOS Importance Engine.

Covers the five behaviors required by the contract:

1. ``compute`` returns valid ranges and a fully populated explanation dict.
2. ``update_memory`` returns a new object and never mutates its input.
3. Category thresholds map raw scores to ``low`` / ``medium`` / ``high``.
4. Importance is monotonic in the semantic score.
5. Importance decays with recency.

Plus regression checks for explicit emphasis saturation, absence of a
``semantic_score`` (derivation from the memory), and the confidence source
table from ``docs/Algorithms.md`` section 4.3.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from memos.config.settings import Settings
from memos.domain.memory import (
    MemoryObject,
    MemoryType,
    SemanticScore,
    now_utc,
)
from memos.engines.importance import (
    HIGH_IMPORTANCE_THRESHOLD,
    LOW_IMPORTANCE_THRESHOLD,
    ImportanceEngine,
)

VALID_CATEGORIES = ("low", "medium", "high")


# ---------------------------------------------------------------------------
# Fixtures & builders
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> ImportanceEngine:
    return ImportanceEngine(Settings())


def build_memory(**overrides: object) -> MemoryObject:
    """Build a MemoryObject with stable, neutral defaults."""
    defaults: dict = {
        "content": "A neutral memory",
        "type": MemoryType.GENERAL,
        "tags": [],
        "metadata": {},
        "access_count": 0,
        "last_accessed_at": None,
        "created_at": now_utc(),
        "importance": 0.5,
        "importance_category": "medium",
        "confidence": 0.5,
    }
    defaults.update(overrides)
    return MemoryObject(**defaults)


def uniform_semantic(value: float) -> SemanticScore:
    """A SemanticScore whose four dimensions share one value."""
    return SemanticScore(
        attention=value,
        repetition=value,
        relevance=value,
        emotional_intensity=value,
    )


# ---------------------------------------------------------------------------
# 1. Default compute returns valid ranges
# ---------------------------------------------------------------------------


def test_compute_returns_valid_ranges(engine: ImportanceEngine) -> None:
    score = engine.compute(build_memory())

    assert 0.0 <= score.raw_score <= 1.0
    assert 0.0 <= score.importance <= 100.0
    assert score.category in VALID_CATEGORIES
    assert 0.0 <= score.confidence <= 1.0
    assert set(score.components) == {
        "emphasis",
        "type_weight",
        "relationship_density",
        "retrieval_frequency",
        "age_factor",
        "semantic_score",
        "confidence",
    }


def test_compute_clamps_out_of_range_semantic_inputs(engine: ImportanceEngine) -> None:
    score = engine.compute(
        build_memory(),
        semantic_score=SemanticScore(attention=2.0, repetition=-1.0, relevance=3.0, emotional_intensity=5.0),
    )

    assert 0.0 <= score.raw_score <= 1.0
    assert 0.0 <= score.importance <= 100.0


# ---------------------------------------------------------------------------
# 2. update_memory never mutates the input
# ---------------------------------------------------------------------------


def test_update_memory_does_not_mutate_input(engine: ImportanceEngine) -> None:
    original = build_memory(
        content="Remember the project deadline",
        tags=["work", "deadline"],
        access_count=3,
    )
    snapshot = original.to_dict()

    updated = engine.update_memory(original)

    # The input is byte-for-byte unchanged.
    assert original.to_dict() == snapshot
    # A different object is returned with importance fields populated.
    assert updated is not original
    assert updated.importance_category in VALID_CATEGORIES
    assert 0.0 <= updated.confidence <= 1.0
    # Identity payload is carried over untouched.
    assert updated.memory_id == original.memory_id
    assert updated.content == original.content
    assert updated.tags == original.tags
    assert updated.version == original.version
    assert updated.created_at == original.created_at


# ---------------------------------------------------------------------------
# 3. Category thresholds
# ---------------------------------------------------------------------------


def test_explicit_emphasis_saturates_to_high(engine: ImportanceEngine) -> None:
    score = engine.compute(build_memory(metadata={"emphasis": True}))

    assert score.category == "high"
    assert score.raw_score == 1.0
    assert score.importance == 100.0


def test_fresh_general_memory_is_low_category(engine: ImportanceEngine) -> None:
    score = engine.compute(build_memory(content="quick", type=MemoryType.GENERAL))

    assert score.category == "low"
    assert score.raw_score < LOW_IMPORTANCE_THRESHOLD


def test_boundary_thresholds_are_exclusive(engine: ImportanceEngine) -> None:
    # ``low`` is strictly below the low threshold; ``high`` strictly above the
    # high threshold; the middle band is ``medium``.
    assert engine._categorize(0.0) == "low"
    assert engine._categorize(LOW_IMPORTANCE_THRESHOLD) == "medium"  # 0.33 inclusive
    assert engine._categorize(LOW_IMPORTANCE_THRESHOLD + 1e-9) == "medium"
    assert engine._categorize(HIGH_IMPORTANCE_THRESHOLD) == "medium"  # 0.66 inclusive
    assert engine._categorize(HIGH_IMPORTANCE_THRESHOLD - 1e-9) == "medium"
    assert engine._categorize(1.0) == "high"


# ---------------------------------------------------------------------------
# 4. Monotonicity with a higher semantic score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lower,higher", [(0.1, 0.9), (0.3, 0.7), (0.0, 0.5)])
def test_importance_is_monotonic_in_semantic_score(
    engine: ImportanceEngine, lower: float, higher: float
) -> None:
    memory = build_memory(content="Shared content across the comparison.")

    weak = engine.compute(memory, semantic_score=uniform_semantic(lower))
    strong = engine.compute(memory, semantic_score=uniform_semantic(higher))

    assert strong.raw_score > weak.raw_score
    assert strong.importance > weak.importance


# ---------------------------------------------------------------------------
# 5. Recency decay behavior
# ---------------------------------------------------------------------------


def test_recency_decay_with_last_accessed_at(engine: ImportanceEngine) -> None:
    fresh = build_memory(content="identical content", last_accessed_at=now_utc())
    stale = build_memory(
        content="identical content",
        last_accessed_at=now_utc() - timedelta(days=365),
    )

    fresh_score = engine.compute(fresh)
    stale_score = engine.compute(stale)

    # An older, identical memory must never outrank a freshly accessed one.
    assert stale_score.raw_score < fresh_score.raw_score
    assert stale_score.importance < fresh_score.importance


def test_recency_falls_back_to_created_at(engine: ImportanceEngine) -> None:
    old = build_memory(
        content="identical content",
        created_at=now_utc() - timedelta(days=365),
        last_accessed_at=None,
    )
    new = build_memory(
        content="identical content",
        created_at=now_utc(),
        last_accessed_at=None,
    )

    old_score = engine.compute(old)
    new_score = engine.compute(new)

    assert old_score.raw_score < new_score.raw_score


def test_recency_decay_is_monotonic_over_time(engine: ImportanceEngine) -> None:
    base = now_utc()
    raw_scores = [
        engine.compute(
            build_memory(content="same", last_accessed_at=base - timedelta(days=days))
        ).raw_score
        for days in (0, 10, 100, 1000)
    ]

    for earlier, later in zip(raw_scores, raw_scores[1:]):
        assert later < earlier


# ---------------------------------------------------------------------------
# Additional contract coverage
# ---------------------------------------------------------------------------


def test_compute_without_semantic_score_derives_components(
    engine: ImportanceEngine,
) -> None:
    memory = build_memory(
        content="A" * 600,
        tags=["one", "two", "three"],
        access_count=5,
        metadata={"emotional_intensity": 0.8},
    )

    score = engine.compute(memory)  # semantic_score defaults to None

    semantic_floor = 0.4 * 1.0 + 0.2 * 0.5 + 0.15 * 0.8  # attention 1.0, rep 0.5, emo 0.8
    assert score.components["semantic_score"] > semantic_floor
    assert score.raw_score > 0.0


def test_confidence_source_table(engine: ImportanceEngine) -> None:
    verified = engine.compute(
        build_memory(metadata={"confidence_source": "SYSTEM_VERIFIED"}, confidence=0.1)
    ).confidence
    inferred = engine.compute(
        build_memory(metadata={"confidence_source": "INFERRED"}, confidence=0.1)
    ).confidence

    # SYSTEM_VERIFIED (0.95) must score far more reliable than INFERRED (0.50).
    assert verified > inferred
    assert 0.0 <= verified <= 1.0
    assert 0.0 <= inferred <= 1.0


def test_manual_assignment_uses_caller_provided_value(engine: ImportanceEngine) -> None:
    score = engine.compute(
        build_memory(
            metadata={"confidence_source": "MANUAL_ASSIGNMENT", "confidence": 0.42}
        )
    )

    # 0.7 * 0.42 + 0.3 * 0.50 = 0.444
    assert score.confidence == pytest.approx(0.444, abs=1e-9)