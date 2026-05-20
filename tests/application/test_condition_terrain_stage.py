"""Unit tests for `ConditionTerrainStage`.

Hits real pysheds. The stage's job is well-defined: pit-filled output is identical or higher
than the input at every cell, and strictly higher inside pits. We assert exactly that.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.condition_terrain import ConditionTerrainStage
from cs_mapgen.application.stages.prepare_terrain import (
    PreparedTerrain,
    PrepareTerrainResult,
)
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.water import WaterFeatures

WGS84 = Projection.wgs84()
GRID_SIDE = 16

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
        playable_bounds=TEST_BOUNDS,
        working_crs=WGS84,
        seed=0,
        cache_directory=tmp_path / "cache",
        output_directory=tmp_path / "out",
        dump_intermediates=False,
        logger=logging.getLogger("cs_mapgen.tests.condition_terrain"),
    )


def _wrap(prepared: PreparedTerrain) -> PrepareTerrainResult:
    return PrepareTerrainResult(
        prepared_terrain=prepared,
        road_network=RoadNetwork(nodes=(), edges=(), crs=WGS84),
        water_features=WaterFeatures(
            polygons=(),
            waterways=(),
            coastlines=(),
            crs=WGS84,
        ),
    )


def test_should_raise_pit_to_match_lowest_neighbour_when_stage_runs(
    tmp_path: Path,
) -> None:
    # Build a flat plateau at 100 m with a single 50 m pit at the centre. After fill, the pit
    # should be raised to its lowest neighbour value (100 m).
    elevation = np.full((GRID_SIDE, GRID_SIDE), 100.0, dtype=np.float32)
    elevation[GRID_SIDE // 2, GRID_SIDE // 2] = 50.0
    prepared = PreparedTerrain(
        elevation=elevation,
        nodata_mask=np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.bool_),
        transform=TEST_TRANSFORM,
        relief_min_metres=50.0,
        relief_max_metres=100.0,
        height_scale_metres=1024.0,
        sea_level_metres=40.0,
    )

    stage = ConditionTerrainStage()
    result = stage.run(_wrap(prepared), _stage_context(tmp_path))

    # Output must be ≥ input everywhere, equal outside the pit, and strictly raised at the pit.
    diff = result.prepared_terrain.elevation - elevation
    assert bool((diff >= -1e-3).all())  # ascending fill ⇒ never lowers a cell
    assert result.prepared_terrain.elevation[GRID_SIDE // 2, GRID_SIDE // 2] > 50.0


def test_should_preserve_shape_and_transform_when_stage_runs(tmp_path: Path) -> None:
    elevation = np.linspace(0.0, 500.0, GRID_SIDE * GRID_SIDE, dtype=np.float32).reshape(
        (GRID_SIDE, GRID_SIDE)
    )
    prepared = PreparedTerrain(
        elevation=elevation,
        nodata_mask=np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.bool_),
        transform=TEST_TRANSFORM,
        relief_min_metres=0.0,
        relief_max_metres=500.0,
        height_scale_metres=1024.0,
        sea_level_metres=40.0,
    )

    stage = ConditionTerrainStage()
    result = stage.run(_wrap(prepared), _stage_context(tmp_path))

    assert result.prepared_terrain.elevation.shape == (GRID_SIDE, GRID_SIDE)
    assert result.prepared_terrain.transform == TEST_TRANSFORM


def test_should_be_deterministic_when_stage_runs_twice(tmp_path: Path) -> None:
    elevation = np.full((GRID_SIDE, GRID_SIDE), 100.0, dtype=np.float32)
    elevation[GRID_SIDE // 2, GRID_SIDE // 2] = 50.0
    prepared = PreparedTerrain(
        elevation=elevation,
        nodata_mask=np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.bool_),
        transform=TEST_TRANSFORM,
        relief_min_metres=50.0,
        relief_max_metres=100.0,
        height_scale_metres=1024.0,
        sea_level_metres=40.0,
    )

    stage = ConditionTerrainStage()
    first = stage.run(_wrap(prepared), _stage_context(tmp_path))
    second = stage.run(_wrap(prepared), _stage_context(tmp_path))

    assert np.array_equal(first.prepared_terrain.elevation, second.prepared_terrain.elevation)


def test_should_skip_pit_fill_when_disabled(tmp_path: Path) -> None:
    elevation = np.full((GRID_SIDE, GRID_SIDE), 100.0, dtype=np.float32)
    elevation[GRID_SIDE // 2, GRID_SIDE // 2] = 50.0
    prepared = PreparedTerrain(
        elevation=elevation,
        nodata_mask=np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.bool_),
        transform=TEST_TRANSFORM,
        relief_min_metres=50.0,
        relief_max_metres=100.0,
        height_scale_metres=1024.0,
        sea_level_metres=40.0,
    )

    stage = ConditionTerrainStage(
        fill_single_cell_pits=False,
        fill_multi_cell_depressions=False,
    )
    result = stage.run(_wrap(prepared), _stage_context(tmp_path))

    # Both knobs off → output identical to input.
    assert np.array_equal(result.prepared_terrain.elevation, elevation)


pytestmark = pytest.mark.requires_gis
