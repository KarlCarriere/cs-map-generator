"""Composition root: build the production pipeline by wiring real adapters.

This module is the only place in the project where the infrastructure layer is imported
alongside the application layer. CLI and HTTP entry points call into here to obtain a fully
wired `Pipeline`. Tests inject fakes via `build_pipeline_with` so they never touch the network.
"""

from __future__ import annotations

from cs_mapgen.application.pipeline import Pipeline, PipelineBuilder
from cs_mapgen.application.ports import (
    ArtifactStore,
    DEMSource,
    ExportTarget,
    OSMSource,
    OSMWaterSource,
    Reprojector,
)
from cs_mapgen.config.settings import Settings
from cs_mapgen.infrastructure.artifact_store import FilesystemArtifactStore
from cs_mapgen.infrastructure.dem import SRTMDEMSource
from cs_mapgen.infrastructure.export import CS1ExportTarget, CS2ExportTarget
from cs_mapgen.infrastructure.osm import OSMnxRoadSource, OSMnxWaterSource
from cs_mapgen.infrastructure.projection import PyprojReprojector

TARGET_REGISTRY: dict[str, type[ExportTarget]] = {
    CS1ExportTarget.target_id: CS1ExportTarget,
    CS2ExportTarget.target_id: CS2ExportTarget,
}

# Per-target internal heightmap side. CS2 carries a 4× wider worldmap layer at the same
# metres-per-pixel scale as the heightmap, so we render the whole worldmap extent at full PNG
# resolution (4096 px) and let the export adapter crop the centre 1024 px for heightmap.png.
# CS1 stays at the historical default (1081, matching the CS1 heightmap PNG side + buffer).
TARGET_HEIGHTMAP_SIDE_PIXELS: dict[str, int] = {
    CS1ExportTarget.target_id: 1081,
    CS2ExportTarget.target_id: 4096,
}


def build_production_pipeline(settings: Settings, target_id: str) -> Pipeline:
    if target_id not in TARGET_REGISTRY:
        raise ValueError(
            f"Unknown export target {target_id!r}. Known targets: {sorted(TARGET_REGISTRY)}"
        )
    dem_source = SRTMDEMSource(
        cache_directory=settings.cache_directory,
        base_url=settings.srtm_base_url,
    )
    osm_source = OSMnxRoadSource()
    water_source = OSMnxWaterSource(cache_directory=settings.cache_directory)
    reprojector = PyprojReprojector()
    artifact_store = FilesystemArtifactStore(root_directory=settings.output_directory)
    export_target = TARGET_REGISTRY[target_id](reprojector=reprojector)
    return build_pipeline_with(
        dem_source=dem_source,
        osm_source=osm_source,
        water_source=water_source,
        reprojector=reprojector,
        artifact_store=artifact_store,
        export_target=export_target,
        target_side_pixels=TARGET_HEIGHTMAP_SIDE_PIXELS.get(target_id),
    )


def build_pipeline_with(
    *,
    dem_source: DEMSource,
    osm_source: OSMSource,
    water_source: OSMWaterSource,
    reprojector: Reprojector,
    artifact_store: ArtifactStore,
    export_target: ExportTarget,
    target_side_pixels: int | None = None,
) -> Pipeline:
    return (
        PipelineBuilder()
        .with_dem_source(dem_source)
        .with_osm_source(osm_source)
        .with_water_source(water_source)
        .with_reprojector(reprojector)
        .with_artifact_store(artifact_store)
        .with_export_target(export_target)
        .build_terrain_and_roads(target_side_pixels=target_side_pixels)
    )
