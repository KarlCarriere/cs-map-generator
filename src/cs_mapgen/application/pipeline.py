"""Pipeline orchestrator and builder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cs_mapgen.application.ports import (
    ArtifactStore,
    DEMSource,
    ExportTarget,
    OSMSource,
    Reprojector,
)
from cs_mapgen.application.stage import Stage, StageContext

StageObserver = Callable[[str, int, int], None]
"""Called as `(stage_name, stage_index, total_stages)`. `stage_index` is zero-based."""


class PipelineConfigurationError(RuntimeError):
    """Raised when the builder is asked to build before all required ports are wired."""


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Whatever the final stage returned, plus stage-by-stage trace for debuggability."""

    final_output: object
    stage_outputs: tuple[tuple[str, object], ...]


class Pipeline:
    """Runs a fixed sequence of `Stage`s, threading each stage's output into the next.

    Determinism contract: the stage order is fixed at construction and the context is frozen for
    the whole run. No stage may rely on iteration order of unsorted dicts.
    """

    def __init__(self, stages: tuple[Stage, ...]) -> None:
        if not stages:
            raise PipelineConfigurationError("Pipeline must contain at least one stage")
        self._stages = stages

    @property
    def stages(self) -> tuple[Stage, ...]:
        return self._stages

    def run(
        self,
        initial_input: object,
        context: StageContext,
        *,
        on_stage_start: StageObserver | None = None,
        on_stage_end: StageObserver | None = None,
    ) -> PipelineResult:
        trace: list[tuple[str, object]] = []
        current: object = initial_input
        total = len(self._stages)
        for index, stage in enumerate(self._stages):
            context.logger.info("stage.start", extra={"stage": stage.name})
            if on_stage_start is not None:
                on_stage_start(stage.name, index, total)
            current = stage.run(current, context)
            trace.append((stage.name, current))
            context.logger.info("stage.end", extra={"stage": stage.name})
            if on_stage_end is not None:
                on_stage_end(stage.name, index, total)
        return PipelineResult(final_output=current, stage_outputs=tuple(trace))


class PipelineBuilder:
    """Wires the MVP terrain+roads pipeline by injecting concrete ports.

    The builder enforces presence of every required port before producing a `Pipeline`. It
    deliberately does not import any infrastructure module — concrete adapters are passed in
    from the composition root (CLI or HTTP entry point).
    """

    def __init__(self) -> None:
        self._dem_source: DEMSource | None = None
        self._osm_source: OSMSource | None = None
        self._reprojector: Reprojector | None = None
        self._export_target: ExportTarget | None = None
        self._artifact_store: ArtifactStore | None = None

    def with_dem_source(self, source: DEMSource) -> PipelineBuilder:
        self._dem_source = source
        return self

    def with_osm_source(self, source: OSMSource) -> PipelineBuilder:
        self._osm_source = source
        return self

    def with_reprojector(self, reprojector: Reprojector) -> PipelineBuilder:
        self._reprojector = reprojector
        return self

    def with_export_target(self, target: ExportTarget) -> PipelineBuilder:
        self._export_target = target
        return self

    def with_artifact_store(self, store: ArtifactStore) -> PipelineBuilder:
        self._artifact_store = store
        return self

    def build_terrain_and_roads(self) -> Pipeline:
        # Local imports keep the application package free of stage-construction at import time
        # and make the wiring explicit at build time.
        from cs_mapgen.application.stages.compose_map import ComposeMapStage
        from cs_mapgen.application.stages.export_map import ExportMapStage
        from cs_mapgen.application.stages.ingest_dem import IngestDEMStage
        from cs_mapgen.application.stages.ingest_roads import IngestRoadsStage
        from cs_mapgen.application.stages.prepare_roads import PrepareRoadsStage
        from cs_mapgen.application.stages.prepare_terrain import PrepareTerrainStage

        dem_source = self._require(self._dem_source, "dem_source")
        osm_source = self._require(self._osm_source, "osm_source")
        reprojector = self._require(self._reprojector, "reprojector")
        export_target = self._require(self._export_target, "export_target")
        artifact_store = self._require(self._artifact_store, "artifact_store")

        return Pipeline(
            stages=(
                IngestDEMStage(dem_source=dem_source),
                IngestRoadsStage(osm_source=osm_source),
                PrepareTerrainStage(reprojector=reprojector),
                PrepareRoadsStage(reprojector=reprojector),
                ComposeMapStage(target_id=export_target.target_id),
                ExportMapStage(target=export_target, store=artifact_store),
            )
        )

    @staticmethod
    def _require[PortT](port: PortT | None, name: str) -> PortT:
        if port is None:
            raise PipelineConfigurationError(f"PipelineBuilder is missing required port: {name}")
        return port
