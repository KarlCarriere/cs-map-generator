"""Unit tests for `IngestWaterStage`. Uses a fake `OSMWaterSource` — no network."""

from __future__ import annotations

from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.ingest_dem import IngestDEMResult
from cs_mapgen.application.stages.ingest_roads import IngestRoadsResult
from cs_mapgen.application.stages.ingest_water import IngestWaterStage
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.raster import DEMTile
from cs_mapgen.domain.water import WaterFeatures, WaterPolygon
from tests._fakes import FakeOSMWaterSource

WGS84 = Projection.wgs84()
SQUARE_RING = (
    (0.41, 0.41),
    (0.42, 0.41),
    (0.42, 0.42),
    (0.41, 0.42),
    (0.41, 0.41),
)


def _build_upstream_inputs(bounds: GeoBounds) -> IngestRoadsResult:
    import numpy as np

    dem_tile = DEMTile(
        elevation=np.zeros((4, 4), dtype=np.float32),
        transform=(1.0, 0.0, bounds.west, 0.0, -1.0, bounds.north),
        crs=WGS84,
        nodata=-9999.0,
        provider="fake",
        resolution_metres=30.0,
    )
    return IngestRoadsResult(
        ingested_dem=IngestDEMResult(dem_tile=dem_tile),
        road_network=RoadNetwork(nodes=(), edges=(), crs=WGS84),
    )


def test_should_forward_upstream_when_water_source_returns_features(
    stage_context: StageContext,
) -> None:
    features = WaterFeatures(
        polygons=(WaterPolygon(exterior=SQUARE_RING),),
        waterways=(),
        coastlines=(),
        crs=WGS84,
    )
    stage = IngestWaterStage(water_source=FakeOSMWaterSource(features=features))
    upstream = _build_upstream_inputs(stage_context.bounds)

    result = stage.run(upstream, stage_context)

    assert result.ingested_roads is upstream
    assert result.water_features.polygons == (WaterPolygon(exterior=SQUARE_RING),)


def test_should_return_empty_features_when_water_source_finds_no_water(
    stage_context: StageContext,
) -> None:
    stage = IngestWaterStage(water_source=FakeOSMWaterSource())
    upstream = _build_upstream_inputs(stage_context.bounds)

    result = stage.run(upstream, stage_context)

    assert result.water_features.is_empty
    assert result.ingested_roads is upstream


def test_should_be_deterministic_when_stage_runs_twice_with_same_inputs(
    stage_context: StageContext,
) -> None:
    features = WaterFeatures(
        polygons=(WaterPolygon(exterior=SQUARE_RING),),
        waterways=(),
        coastlines=(),
        crs=WGS84,
    )
    stage = IngestWaterStage(water_source=FakeOSMWaterSource(features=features))
    upstream = _build_upstream_inputs(stage_context.bounds)

    first = stage.run(upstream, stage_context)
    second = stage.run(upstream, stage_context)

    assert first.water_features == second.water_features
