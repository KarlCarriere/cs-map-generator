"""Unit tests for the Pipeline orchestrator."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cs_mapgen.application.pipeline import (
    Pipeline,
    PipelineBuilder,
    PipelineConfigurationError,
)
from cs_mapgen.application.stage import StageContext


@dataclass
class _FakeStage:
    name: str
    suffix: str

    def run(self, inputs: object, context: StageContext) -> str:
        del context
        return f"{inputs}->{self.suffix}"


def test_should_thread_outputs_when_pipeline_runs_two_stages(stage_context: StageContext) -> None:
    pipeline = Pipeline(
        stages=(_FakeStage(name="first", suffix="a"), _FakeStage(name="second", suffix="b"))
    )

    result = pipeline.run("seed", stage_context)

    assert result.final_output == "seed->a->b"
    assert tuple(name for name, _ in result.stage_outputs) == ("first", "second")


def test_should_raise_when_pipeline_is_constructed_without_stages() -> None:
    with pytest.raises(PipelineConfigurationError):
        Pipeline(stages=())


def test_should_raise_when_builder_is_missing_a_port() -> None:
    builder = PipelineBuilder()

    with pytest.raises(PipelineConfigurationError, match="dem_source"):
        builder.build_terrain_and_roads()


def test_should_be_deterministic_when_pipeline_runs_twice_with_same_inputs(
    stage_context: StageContext,
) -> None:
    pipeline = Pipeline(
        stages=(_FakeStage(name="first", suffix="a"), _FakeStage(name="second", suffix="b"))
    )

    first = pipeline.run("seed", stage_context)
    second = pipeline.run("seed", stage_context)

    assert first.final_output == second.final_output
