"""Application layer — pipeline orchestration and stage Protocols."""

from cs_mapgen.application.extent_resolver import ExtentResolutionError, resolve_extent
from cs_mapgen.application.pipeline import Pipeline, PipelineBuilder
from cs_mapgen.application.ports import (
    ArtifactStore,
    DEMSource,
    ExportTarget,
    OSMSource,
    Reprojector,
)
from cs_mapgen.application.stage import Stage, StageContext

__all__ = [
    "ArtifactStore",
    "DEMSource",
    "ExportTarget",
    "ExtentResolutionError",
    "OSMSource",
    "Pipeline",
    "PipelineBuilder",
    "Reprojector",
    "Stage",
    "StageContext",
    "resolve_extent",
]
