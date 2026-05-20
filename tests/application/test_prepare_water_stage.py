"""Unit tests for `PrepareWaterStage`. Uses an identity reprojector + offline water fixture."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.condition_terrain import ConditionTerrainResult
from cs_mapgen.application.stages.prepare_terrain import PreparedTerrain
from cs_mapgen.application.stages.prepare_water import PrepareWaterStage
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.water import WaterFeatures, WaterPolygon, Waterway
from tests._fakes import IdentityReprojector

WGS84 = Projection.wgs84()
GRID_SIDE = 64

# Bbox is metric in working CRS — but the IdentityReprojector keeps coordinates unchanged, so
# the test treats coordinates as already-metric in a "fake CRS" matching EPSG:32633. The shape
# of the rasterisation is identical to the production code path; only the units differ.
TEST_BOUNDS = GeoBounds(west=0.4, south=0.4, east=0.6, north=0.6, crs=WGS84)
TEST_TRANSFORM = (
    (TEST_BOUNDS.east - TEST_BOUNDS.west) / GRID_SIDE,
    0.0,
    TEST_BOUNDS.west,
    0.0,
    -(TEST_BOUNDS.north - TEST_BOUNDS.south) / GRID_SIDE,
    TEST_BOUNDS.north,
)


def _stage_context(tmp_path: Path) -> StageContext:
    return StageContext(
        bounds=TEST_BOUNDS,
        target_bounds=TEST_BOUNDS,
        working_crs=WGS84,
        seed=0,
        cache_directory=tmp_path / "cache",
        output_directory=tmp_path / "out",
        dump_intermediates=False,
        logger=logging.getLogger("cs_mapgen.tests.prepare_water"),
    )


def _prepared_terrain() -> PreparedTerrain:
    elevation = np.full((GRID_SIDE, GRID_SIDE), 100.0, dtype=np.float32)
    nodata = np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.bool_)
    return PreparedTerrain(
        elevation=elevation,
        nodata_mask=nodata,
        transform=TEST_TRANSFORM,
        relief_min_metres=0.0,
        relief_max_metres=500.0,
        height_scale_metres=1024.0,
        sea_level_metres=40.0,
    )


def _condition_result(water_features: WaterFeatures) -> ConditionTerrainResult:
    return ConditionTerrainResult(
        prepared_terrain=_prepared_terrain(),
        road_network=RoadNetwork(nodes=(), edges=(), crs=WGS84),
        water_features=water_features,
    )


def test_should_produce_empty_mask_when_water_features_are_empty(tmp_path: Path) -> None:
    stage = PrepareWaterStage(reprojector=IdentityReprojector())
    inputs = _condition_result(WaterFeatures(polygons=(), waterways=(), coastlines=(), crs=WGS84))

    result = stage.run(inputs, _stage_context(tmp_path))

    assert result.water_mask.mask.shape == (GRID_SIDE, GRID_SIDE)
    assert not bool(result.water_mask.mask.any())


def test_should_burn_water_polygon_into_mask(tmp_path: Path) -> None:
    polygon = WaterPolygon(
        exterior=(
            (0.45, 0.45),
            (0.55, 0.45),
            (0.55, 0.55),
            (0.45, 0.55),
            (0.45, 0.45),
        ),
    )
    features = WaterFeatures(
        polygons=(polygon,),
        waterways=(),
        coastlines=(),
        crs=WGS84,
    )
    stage = PrepareWaterStage(reprojector=IdentityReprojector())
    inputs = _condition_result(features)

    result = stage.run(inputs, _stage_context(tmp_path))

    # The polygon covers a 10%-50% band in the centre — at least one cell must be hot.
    assert bool(result.water_mask.mask.any())
    # And the centre cell — definitely inside the polygon — must be water.
    centre = GRID_SIDE // 2
    assert bool(result.water_mask.mask[centre, centre])


def test_should_burn_buffered_waterway_into_mask(tmp_path: Path) -> None:
    # Pixel size in the test transform is `0.2 / 64 ≈ 0.003125` (units carry the WGS84 sham).
    # A river buffer of 20 m → buffer radius 10 m → in our IdentityReprojected sham units this
    # is just 10 of whatever-unit-the-coords-are; we override the width to a value that does
    # produce a visible buffer at this scale.
    waterway = Waterway(
        geometry=((0.42, 0.5), (0.58, 0.5)),
        waterway_class="river",
    )
    features = WaterFeatures(
        polygons=(),
        waterways=(waterway,),
        coastlines=(),
        crs=WGS84,
    )
    stage = PrepareWaterStage(
        reprojector=IdentityReprojector(),
        # 0.01 in our sham units = ~3 pixels wide, enough to register on the 64×64 mask.
        waterway_widths_metres={"river": 0.01},
    )
    inputs = _condition_result(features)

    result = stage.run(inputs, _stage_context(tmp_path))

    centre_row = GRID_SIDE // 2
    assert bool(result.water_mask.mask[centre_row, :].any())


def test_should_skip_waterway_with_unknown_class(tmp_path: Path) -> None:
    waterway = Waterway(
        geometry=((0.42, 0.5), (0.58, 0.5)),
        waterway_class="ditch",  # NOT in default allowlist
    )
    features = WaterFeatures(
        polygons=(),
        waterways=(waterway,),
        coastlines=(),
        crs=WGS84,
    )
    stage = PrepareWaterStage(reprojector=IdentityReprojector())
    inputs = _condition_result(features)

    result = stage.run(inputs, _stage_context(tmp_path))

    assert not bool(result.water_mask.mask.any())


def test_should_be_deterministic_when_stage_runs_twice(tmp_path: Path) -> None:
    polygon = WaterPolygon(
        exterior=(
            (0.45, 0.45),
            (0.55, 0.45),
            (0.55, 0.55),
            (0.45, 0.55),
            (0.45, 0.45),
        ),
    )
    features = WaterFeatures(
        polygons=(polygon,),
        waterways=(),
        coastlines=(),
        crs=WGS84,
    )
    stage = PrepareWaterStage(reprojector=IdentityReprojector())

    first = stage.run(_condition_result(features), _stage_context(tmp_path))
    second = stage.run(_condition_result(features), _stage_context(tmp_path))

    assert np.array_equal(first.water_mask.mask, second.water_mask.mask)


def test_should_forward_prepared_terrain_unchanged(tmp_path: Path) -> None:
    polygon = WaterPolygon(
        exterior=(
            (0.45, 0.45),
            (0.55, 0.45),
            (0.55, 0.55),
            (0.45, 0.55),
            (0.45, 0.45),
        ),
    )
    features = WaterFeatures(
        polygons=(polygon,),
        waterways=(),
        coastlines=(),
        crs=WGS84,
    )
    stage = PrepareWaterStage(reprojector=IdentityReprojector())
    inputs = _condition_result(features)

    result = stage.run(inputs, _stage_context(tmp_path))

    # Elevation values must not have been mutated by the water stage — carving is the
    # quantise stage's job. Compare arrays for byte equality.
    assert np.array_equal(result.prepared_terrain.elevation, inputs.prepared_terrain.elevation)


# Stress / safety: invalid bounds should still produce a valid (empty) mask. Catch-all.
def test_should_produce_correctly_shaped_mask_even_with_micro_polygon(
    tmp_path: Path,
) -> None:
    # A tiny polygon — smaller than any pixel — should at most burn a single pixel via
    # all_touched, never break the rasterisation.
    polygon = WaterPolygon(
        exterior=(
            (0.4999, 0.4999),
            (0.5001, 0.4999),
            (0.5001, 0.5001),
            (0.4999, 0.5001),
            (0.4999, 0.4999),
        ),
    )
    features = WaterFeatures(
        polygons=(polygon,),
        waterways=(),
        coastlines=(),
        crs=WGS84,
    )
    stage = PrepareWaterStage(reprojector=IdentityReprojector())

    result = stage.run(_condition_result(features), _stage_context(tmp_path))

    assert result.water_mask.mask.shape == (GRID_SIDE, GRID_SIDE)
    # With all_touched=True, at least one cell must be flagged.
    assert int(result.water_mask.mask.sum()) >= 1


pytestmark = pytest.mark.requires_gis
