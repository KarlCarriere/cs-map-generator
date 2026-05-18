"""Unit tests for the raster value objects."""

from __future__ import annotations

import numpy as np
import pytest

from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.raster import DEMTile, Heightmap

VALID_TRANSFORM = (1.0, 0.0, 0.0, 0.0, -1.0, 0.0)


def test_should_construct_dem_tile_when_inputs_are_valid() -> None:
    elevation = np.zeros((4, 4), dtype=np.float32)

    tile = DEMTile(
        elevation=elevation,
        transform=VALID_TRANSFORM,
        crs=Projection.wgs84(),
        nodata=-9999.0,
        provider="test",
        resolution_metres=30.0,
    )

    assert tile.shape == (4, 4)


def test_should_reject_dem_tile_when_elevation_is_not_2d() -> None:
    elevation = np.zeros((4,), dtype=np.float32)

    with pytest.raises(ValueError, match="2D"):
        DEMTile(
            elevation=elevation,
            transform=VALID_TRANSFORM,
            crs=Projection.wgs84(),
            nodata=-9999.0,
            provider="test",
            resolution_metres=30.0,
        )


def test_should_reject_dem_tile_when_transform_is_not_6_tuple() -> None:
    elevation = np.zeros((4, 4), dtype=np.float32)

    with pytest.raises(ValueError, match="6-tuple"):
        DEMTile(
            elevation=elevation,
            transform=(1.0, 0.0, 0.0),  # type: ignore[arg-type]
            crs=Projection.wgs84(),
            nodata=-9999.0,
            provider="test",
            resolution_metres=30.0,
        )


def test_should_construct_heightmap_when_pixels_are_uint16_and_dimensions_match() -> None:
    bounds = GeoBounds(west=0.0, south=0.0, east=1.0, north=1.0, crs=Projection.wgs84())
    pixels = np.zeros((64, 64), dtype=np.uint16)

    heightmap = Heightmap(
        pixels=pixels,
        width=64,
        height=64,
        height_scale_metres=1024.0,
        sea_level_metres=40.0,
        bounds=bounds,
    )

    assert heightmap.pixels.shape == (64, 64)


def test_should_reject_heightmap_when_pixels_are_not_uint16() -> None:
    bounds = GeoBounds(west=0.0, south=0.0, east=1.0, north=1.0, crs=Projection.wgs84())
    pixels = np.zeros((64, 64), dtype=np.float32)

    with pytest.raises(ValueError, match="uint16"):
        Heightmap(
            pixels=pixels,  # type: ignore[arg-type]
            width=64,
            height=64,
            height_scale_metres=1024.0,
            sea_level_metres=40.0,
            bounds=bounds,
        )


def test_should_reject_heightmap_when_sea_level_exceeds_height_scale() -> None:
    bounds = GeoBounds(west=0.0, south=0.0, east=1.0, north=1.0, crs=Projection.wgs84())
    pixels = np.zeros((64, 64), dtype=np.uint16)

    with pytest.raises(ValueError, match="sea_level_metres"):
        Heightmap(
            pixels=pixels,
            width=64,
            height=64,
            height_scale_metres=1024.0,
            sea_level_metres=2048.0,
            bounds=bounds,
        )
