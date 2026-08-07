"""Unit tests for the MemOS Importance Engine.

Covers the behaviors required by the contract:

1. ``compute`` returns valid ranges and a fully populated explanation dict.
2. ``update_memory`` returns a new object and never mutates its input.
3. Category bands map raw scores to the documented 5-band scheme
   (``negligible`` / ``low`` / ``moderate`` / ``high`` / ``critical``) per
   Algorithms.md §3.2, including the 20/21, 40/41, 60/61, 80/81 boundaries.
4. Importance is monotonic in the semantic score.
5. Importance decays with recency.

Plus regression checks for explicit emphasis saturation, absence of a
``semantic_score`` (derivation from the memory), the confidence source table
from ``docs/Algorithms.md`` section 4.3 (fixed values, no blending),
``MANUAL_ASSIGNMENT`` validation, and NaN-safety of numeric metadata inputs.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from memos.config.settings import Settings
from memos.domain.exceptions import ValidationError
from memos.domain.memory import (
    MemoryObject,
    MemoryType,
    SemanticScore,
    now_utc,
)
from memos.engines.importance import (
    HIGH_BAND_UPPER,
    LOW_BAND_UPPER,
    MODERATE_BAND_UPPER,
    NEGLIGIBLE_BAND_UPPER,
    ImportanceEngine,
)

VALID_CATEGORIES = ("negligible", "low", "moderate", "high", "critical")


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
        "type": MemoryType.SEMANTIC,
        "tags": [],
        "metadata": {},
        "access_count": 0,
        "last_accessed_at": None,
        "created_at": now_utc(),
        "importance": 0.5,
        "importance_category": "negligible",
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
# 1. Default compute returns valid ranges & explanation payload
# ---------------------------------------------------------------------------


def test_compute_returns_valid_ranges(engine: ImportanceEngine) -> None:
    score = engine.compute(build_memory())

    assert 0.0 <= score.raw_score <= 1.0
    assert 0.0 <= score.importance <= 100.0
    # Scale reconciliation: importance is the 0..100 score, raw_score its
    # normalized value in [0, 1] (Algorithms.md AL-003 / §6.1).
    assert score.raw_score == pytest.approx(score.importance / 100.0)
    assert score.category in VALID_CATEGORIES
    assert 0.0 <= score.confidence <= 1.0
    # Documentation (§3.6): explanation carries the method id, a timestamp,
    # every factor, and the resolved confidence source.
    assert score.components["method"] == "memos.importance.v1"
    assert isinstance(score.components["last_calculated"], str)
    assert "last_calculated" in score.components
    assert set(score.components) == {
        "method",
        "last_calculated",
        "emphasis",
        "type_weight",
        "relationship_density",
        "retrieval_frequency",
        "age_factor",
        "semantic_score",
        "confidence_source",
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
# 3. Category bands
# ---------------------------------------------------------------------------


def test_explicit_emphasis_saturates_to_critical(engine: ImportanceEngine) -> None:
    score = engine.compute(build_memory(metadata={"emphasis": True}))

    assert score.category == "critical"
    assert score.raw_score == 1.0
    assert score.importance == 100.0


def test_fresh_semantic_memory_is_low_category(engine: ImportanceEngine) -> None:
    # Doc example (Algorithms.md §3.5): a fresh SEMANTIC memory with no
    # relationships produces approximately 26 on the 0..100 scale -> low.
    score = engine.compute(build_memory())

    assert score.category == "low"
    assert NEGLIGIBLE_BAND_UPPER < score.raw_score <= LOW_BAND_UPPER


def test_fresh_working_memory_is_negligible_category(engine: ImportanceEngine) -> None:
    score = engine.compute(build_memory(content="quick", type=MemoryType.WORKING))

    assert score.category == "negligible"
    assert score.raw_score <= NEGLIGIBLE_BAND_UPPER


def test_connected_memory_is_moderate_category(engine: ImportanceEngine) -> None:
    # EPISODIC (T=40 -> 14) + R=8 (24) + recency (~5) + semantics (~1) ~= 44.
    score = engine.compute(
        build_memory(type=MemoryType.EPISODIC, metadata={"relationship_count": 8})
    )

    assert score.category == "moderate"
    assert LOW_BAND_UPPER < score.raw_score <= MODERATE_BAND_UPPER


def test_heavily_connected_frequent_memory_is_high_category(engine: ImportanceEngine) -> None:
    # Doc example (Algorithms.md §3.5): a heavily connected, frequently
    # retrieved SEMANTIC memory approaches ~66 on the 0..100 scale -> high.
    score = engine.compute(
        build_memory(
            type=MemoryType.SEMANTIC,
            metadata={"relationship_count": 10, "retrieval_count": 10},
        )
    )

    assert score.category == "high"
    assert MODERATE_BAND_UPPER < score.raw_score <= HIGH_BAND_UPPER


@pytest.mark.parametrize(
    "raw_score,expected_category",
    [
        # 0–20 -> negligible (0.20 inclusive).
        (0.0, "negligible"),
        (NEGLIGIBLE_BAND_UPPER, "negligible"),  # 0.20 -> raw = 20/100
        (0.21, "low"),                          # 21/100 boundary
        # 21–40 -> low (0.40 inclusive).
        (LOW_BAND_UPPER, "low"),                # 0.40 -> raw = 40/100
        (0.41, "moderate"),                     # 41/100 boundary
        # 41–60 -> moderate (0.60 inclusive).
        (MODERATE_BAND_UPPER, "moderate"),      # 0.60 -> raw = 60/100
        (0.61, "high"),                         # 61/100 boundary
        # 61–80 -> high (0.80 inclusive).
        (HIGH_BAND_UPPER, "high"),              # 0.80 -> raw = 80/100
        (0.81, "critical"),                     # 81/100 boundary
        # 81–100 -> critical.
        (1.0, "critical"),
    ],
)
def test_category_bands_at_documented_boundaries(
    engine: ImportanceEngine, raw_score: float, expected_category: str
) -> None:
    assert engine._categorize(raw_score) == expected_category


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


# ---------------------------------------------------------------------------
# Confidence (docs/Algorithms.md section 4.3)
# ---------------------------------------------------------------------------


def test_system_verified_confidence_is_exact_no_blend(engine: ImportanceEngine) -> None:
    # A stored confidence of 0.0 must NOT dilute the documented baseline:
    # the source maps directly to its fixed value (no 0.7/0.3 blend).
    score = engine.compute(
        build_memory(metadata={"confidence_source": "SYSTEM_VERIFIED"}, confidence=0.0)
    )

    assert score.confidence == pytest.approx(0.95, abs=1e-12)
    assert score.components["confidence_source"] == "SYSTEM_VERIFIED"


def test_confidence_source_table(engine: ImportanceEngine) -> None:
    verified = engine.compute(
        build_memory(metadata={"confidence_source": "SYSTEM_VERIFIED"}, confidence=0.1)
    ).confidence
    repeated = engine.compute(
        build_memory(metadata={"confidence_source": "REPEATED_OBSERVATION"}, confidence=0.1)
    ).confidence
    inferred = engine.compute(
        build_memory(metadata={"confidence_source": "INFERRED"}, confidence=0.1)
    ).confidence

    # Documented fixed base values (no blending).
    assert verified == pytest.approx(0.95)
    assert repeated == pytest.approx(0.80)
    assert inferred == pytest.approx(0.50)
    assert verified > repeated > inferred
    assert 0.0 <= verified <= 1.0
    assert 0.0 <= repeated <= 1.0
    assert 0.0 <= inferred <= 1.0


def test_manual_assignment_uses_caller_provided_value(engine: ImportanceEngine) -> None:
    score = engine.compute(
        build_memory(
            metadata={"confidence_source": "MANUAL_ASSIGNMENT", "confidence": 0.42}
        )
    )

    # The caller-provided value is used verbatim (clamped to [0, 1]).
    assert score.confidence == pytest.approx(0.42, abs=1e-12)
    assert score.components["confidence_source"] == "MANUAL_ASSIGNMENT"


def test_manual_assignment_missing_value_raises(engine: ImportanceEngine) -> None:
    with pytest.raises(ValidationError):
        engine.compute(build_memory(metadata={"confidence_source": "MANUAL_ASSIGNMENT"}))


@pytest.mark.parametrize("bad_value", ["garbage", float("nan"), float("inf"), None])
def test_manual_assignment_invalid_value_raises(
    engine: ImportanceEngine, bad_value: object
) -> None:
    with pytest.raises(ValidationError):
        engine.compute(
            build_memory(
                metadata={"confidence_source": "MANUAL_ASSIGNMENT", "confidence": bad_value}
            )
        )


def test_missing_source_falls_back_to_stored_confidence(engine: ImportanceEngine) -> None:
    score = engine.compute(build_memory(confidence=0.37))

    assert score.confidence == pytest.approx(0.37, abs=1e-12)
    assert score.components["confidence_source"] == "STORED"


# ---------------------------------------------------------------------------
# NaN / non-finite metadata inputs are sanitized
# ---------------------------------------------------------------------------


def test_nan_and_garbage_metadata_are_sanitized(engine: ImportanceEngine) -> None:
    score = engine.compute(
        build_memory(
            metadata={
                "relationship_count": float("nan"),
                "emphasis": float("nan"),
                "retrieval_count": "garbage",
                "emotional_intensity": float("inf"),
            }
        )
    )

    # None of the non-finite inputs may poison the formula or raise.
    assert 0.0 <= score.raw_score <= 1.0
    assert 0.0 <= score.importance <= 100.0
    assert score.category in VALID_CATEGORIES
    assert 0.0 <= score.confidence <= 1.0
    assert score.components["relationship_density"] == 0.0
    assert score.components["emphasis"] == 0.0
    assert score.components["retrieval_frequency"] == 0.0
    assert score.components["semantic_score"] >= 0.0