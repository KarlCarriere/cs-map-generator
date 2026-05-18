"""Unit tests for the StageContext."""

from __future__ import annotations

from cs_mapgen.application.stage import StageContext


def test_should_produce_deterministic_rng_stream_when_seed_is_fixed(
    stage_context: StageContext,
) -> None:
    first_stream = stage_context.rng().integers(0, 100, size=5)
    second_stream = stage_context.rng().integers(0, 100, size=5)

    assert list(first_stream) == list(second_stream)
