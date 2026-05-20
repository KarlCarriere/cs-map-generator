"""Unit tests for the water-carve-depth behaviour of `QuantizeHeightmapStage`.

Focus: every test exercises exactly one carving invariant in complete isolation. No GIS
dependencies are imported — the stage's inputs are pure NumPy arrays, so all six tests run
without the optional `gis` extras.

Encoding inverse (used to convert quantised uint16 pixels back to metres):

    elevation_metres ≈ pixel_value / UINT16_MAX_VALUE * height_scale_metres

This is the absolute encoding applied by `_absolute_encode` inside the stage. Rounding is
involved (one `round()` call), so assertions use tolerances equal to half a quantisation step
rather than exact float equality.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.prepare_terrain import PreparedTerrain
from cs_mapgen.application.stages.prepare_water import PrepareWaterResult
from cs_mapgen.application.stages.quantize_heightmap import (
    DEFAULT_WATER_CARVE_DEPTH_METRES,
    MIN_WATER_CARVE_QUANTISATION_STEPS,
    UINT16_MAX_VALUE,
    QuantizeHeightmapStage,
)
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.water import WaterMask

# ---------------------------------------------------------------------------
# Shared grid constants
# ---------------------------------------------------------------------------

WGS84 = Projection.wgs84()
# Must be >= MIN_HEIGHTMAP_SIDE_PIXELS (32) — Heightmap.__post_init__ enforces this.
GRID_SIDE = 32

TEST_BOUNDS = GeoBounds(west=0.4, south=0.4, east=0.6, north=0.6, crs=WGS84)
TEST_TRANSFORM = (
    (TEST_BOUNDS.east - TEST_BOUNDS.west) / GRID_SIDE,
    0.0,
    TEST_BOUNDS.west,
    0.0,
    -(TEST_BOUNDS.north - TEST_BOUNDS.south) / GRID_SIDE,
    TEST_BOUNDS.north,
)

# Domain parameters that all tests share unless overridden.
HEIGHT_SCALE_METRES = 1024.0
SEA_LEVEL_METRES = 40.0

# Half a quantisation step — the maximum encoding error after round().
_QUANTISATION_STEP_METRES = HEIGHT_SCALE_METRES / UINT16_MAX_VALUE
_HALF_STEP = _QUANTISATION_STEP_METRES / 2.0


# ---------------------------------------------------------------------------
# Helpers: factories, NOT assertions
# ---------------------------------------------------------------------------


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
        logger=logging.getLogger("cs_mapgen.tests.quantize_heightmap"),
    )


def _uniform_terrain(elevation_metres: float) -> PreparedTerrain:
    """A flat GRID_SIDE x GRID_SIDE grid at a fixed elevation with no nodata."""
    elevation = np.full((GRID_SIDE, GRID_SIDE), elevation_metres, dtype=np.float32)
    return PreparedTerrain(
        elevation=elevation,
        nodata_mask=np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.bool_),
        transform=TEST_TRANSFORM,
        relief_min_metres=elevation_metres,
        relief_max_metres=elevation_metres,
        height_scale_metres=HEIGHT_SCALE_METRES,
        sea_level_metres=SEA_LEVEL_METRES,
    )


def _all_water_mask() -> WaterMask:
    """A water mask where every cell is flagged as water."""
    return WaterMask(
        mask=np.ones((GRID_SIDE, GRID_SIDE), dtype=np.bool_),
        transform=TEST_TRANSFORM,
        crs=WGS84,
    )


def _no_water_mask() -> WaterMask:
    """A water mask where no cell is flagged as water."""
    return WaterMask(
        mask=np.zeros((GRID_SIDE, GRID_SIDE), dtype=np.bool_),
        transform=TEST_TRANSFORM,
        crs=WGS84,
    )


def _prepare_water_result(
    terrain: PreparedTerrain,
    water_mask: WaterMask,
) -> PrepareWaterResult:
    return PrepareWaterResult(
        prepared_terrain=terrain,
        road_network=RoadNetwork(nodes=(), edges=(), crs=WGS84),
        water_mask=water_mask,
    )


def _decode_pixel_to_metres(pixel_value: int) -> float:
    """Invert the absolute uint16 encoding: pixel → metres."""
    return pixel_value / UINT16_MAX_VALUE * HEIGHT_SCALE_METRES


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_should_carve_water_cell_to_sea_level_minus_five_metres_when_using_default_depth(
    tmp_path: Path,
) -> None:
    # Arrange: a water cell at 38 m — above sea level (40 m), above the default carve target.
    initial_elevation_metres = 38.0
    expected_carve_target_metres = SEA_LEVEL_METRES - DEFAULT_WATER_CARVE_DEPTH_METRES  # 35.0

    terrain = _uniform_terrain(initial_elevation_metres)
    inputs = _prepare_water_result(terrain, _all_water_mask())
    stage = QuantizeHeightmapStage()  # default depth = 5.0 m

    # Act
    result = stage.run(inputs, _stage_context(tmp_path))

    # Assert: every pixel should decode to the carve target (35.0 m) within rounding tolerance.
    centre_pixel = int(result.heightmap.pixels[GRID_SIDE // 2, GRID_SIDE // 2])
    decoded_metres = _decode_pixel_to_metres(centre_pixel)
    assert abs(decoded_metres - expected_carve_target_metres) <= _HALF_STEP


def test_should_carve_water_cell_to_sea_level_minus_configured_depth_when_depth_is_ten_metres(
    tmp_path: Path,
) -> None:
    # Arrange: a water cell at 38 m; custom carve depth of 10 m yields target 30.0 m.
    configured_depth = 10.0
    expected_carve_target_metres = SEA_LEVEL_METRES - configured_depth  # 30.0

    terrain = _uniform_terrain(38.0)
    inputs = _prepare_water_result(terrain, _all_water_mask())
    stage = QuantizeHeightmapStage(water_carve_depth_metres=configured_depth)

    # Act
    result = stage.run(inputs, _stage_context(tmp_path))

    # Assert: decoded elevation must equal the 10 m carve target within rounding tolerance.
    centre_pixel = int(result.heightmap.pixels[GRID_SIDE // 2, GRID_SIDE // 2])
    decoded_metres = _decode_pixel_to_metres(centre_pixel)
    assert abs(decoded_metres - expected_carve_target_metres) <= _HALF_STEP


def test_should_carve_at_least_one_quantisation_step_when_configured_depth_is_zero(
    tmp_path: Path,
) -> None:
    # Arrange: depth=0.0 triggers the floor guard — the stage must still carve at least one
    # quantisation step below sea level so the engine water plane never Z-fights with the
    # terrain mesh. The water cell starts at 50 m (above sea level AND above the floor target
    # of ~39.984 m), so the carving condition fires and the floor applies.
    min_carve_depth_metres = _QUANTISATION_STEP_METRES * MIN_WATER_CARVE_QUANTISATION_STEPS
    expected_carve_target_metres = SEA_LEVEL_METRES - min_carve_depth_metres  # ≈ 39.984 m

    terrain = _uniform_terrain(50.0)
    inputs = _prepare_water_result(terrain, _all_water_mask())
    stage = QuantizeHeightmapStage(water_carve_depth_metres=0.0)

    # Act
    result = stage.run(inputs, _stage_context(tmp_path))

    # Assert: decoded elevation must be strictly below sea level and within one step of the
    # floor target — proving the floor was applied, not zero depth.
    centre_pixel = int(result.heightmap.pixels[GRID_SIDE // 2, GRID_SIDE // 2])
    decoded_metres = _decode_pixel_to_metres(centre_pixel)
    assert decoded_metres < SEA_LEVEL_METRES
    assert abs(decoded_metres - expected_carve_target_metres) <= _HALF_STEP


def test_should_leave_water_cell_untouched_when_elevation_is_already_below_carve_target(
    tmp_path: Path,
) -> None:
    # Arrange: a water cell already at 10 m — well below the default carve target (35 m).
    # The stage must NOT raise it; it must stay at its natural sub-sea-level elevation.
    pre_existing_elevation_metres = 10.0

    terrain = _uniform_terrain(pre_existing_elevation_metres)
    inputs = _prepare_water_result(terrain, _all_water_mask())
    stage = QuantizeHeightmapStage()  # default 5 m depth → carve target = 35 m

    # Act
    result = stage.run(inputs, _stage_context(tmp_path))

    # Assert: decoded elevation stays near the original 10 m (not raised to 35 m).
    centre_pixel = int(result.heightmap.pixels[GRID_SIDE // 2, GRID_SIDE // 2])
    decoded_metres = _decode_pixel_to_metres(centre_pixel)
    assert abs(decoded_metres - pre_existing_elevation_metres) <= _HALF_STEP


def test_should_raise_value_error_when_water_carve_depth_is_negative() -> None:
    # Arrange / Act / Assert: constructor must reject negative depths immediately.
    with pytest.raises(ValueError, match="water_carve_depth_metres"):
        QuantizeHeightmapStage(water_carve_depth_metres=-0.1)


def test_should_leave_land_cell_at_original_elevation_when_not_flagged_as_water(
    tmp_path: Path,
) -> None:
    # Arrange: a land cell at 100 m — no water mask coverage. The carving logic must
    # not touch it.
    land_elevation_metres = 100.0

    terrain = _uniform_terrain(land_elevation_metres)
    inputs = _prepare_water_result(terrain, _no_water_mask())
    stage = QuantizeHeightmapStage()

    # Act
    result = stage.run(inputs, _stage_context(tmp_path))

    # Assert: decoded elevation stays near the original 100 m.
    centre_pixel = int(result.heightmap.pixels[GRID_SIDE // 2, GRID_SIDE // 2])
    decoded_metres = _decode_pixel_to_metres(centre_pixel)
    assert abs(decoded_metres - land_elevation_metres) <= _HALF_STEP
