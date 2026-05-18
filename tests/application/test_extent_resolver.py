"""Unit tests for `resolve_extent`.

Covers the lat/lon → metres math at multiple latitudes, the boundary rejections
(antimeridian, pole), and the equivalence between `CenterExtent` and `BoundsExtent` shapes.
"""

from __future__ import annotations

from math import cos, radians

import pytest

from cs_mapgen.application.extent_resolver import (
    EARTH_RADIUS_METRES,
    ExtentResolutionError,
    resolve_extent,
)
from cs_mapgen.domain.extent import BoundsExtent, CenterExtent, GeoPoint
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.target_specs import (
    CS1_TILE_SIDE_METRES,
    CS2_TILE_SIDE_METRES,
)

TWO_PI = 2.0 * 3.141592653589793
METRES_PER_LATITUDE_DEGREE = (TWO_PI * EARTH_RADIUS_METRES) / 360.0

# 0.5% tolerance, per the brief.
WIDTH_TOLERANCE = 0.005

CS1_FULL_RADIUS = 4
CS2_FULL_RADIUS = 10


def _expected_side_metres(tile_side_metres: float, radius_tiles: int) -> float:
    return (2 * radius_tiles + 1) * tile_side_metres


def _width_metres(bounds: GeoBounds, latitude_degrees: float) -> float:
    width_degrees = bounds.east - bounds.west
    metres_per_lon_degree = METRES_PER_LATITUDE_DEGREE * cos(radians(latitude_degrees))
    return width_degrees * metres_per_lon_degree


def _height_metres(bounds: GeoBounds) -> float:
    return (bounds.north - bounds.south) * METRES_PER_LATITUDE_DEGREE


@pytest.mark.parametrize(
    ("latitude", "longitude", "radius_tiles", "target_id", "tile_side"),
    [
        (0.0, 0.0, CS1_FULL_RADIUS, "cs1", CS1_TILE_SIDE_METRES),  # equator
        (45.0, 10.0, CS1_FULL_RADIUS, "cs1", CS1_TILE_SIDE_METRES),  # mid-latitude
        (70.0, -100.0, CS1_FULL_RADIUS, "cs1", CS1_TILE_SIDE_METRES),  # high-latitude
        (0.0, 0.0, CS2_FULL_RADIUS, "cs2", CS2_TILE_SIDE_METRES),
        (45.0, 10.0, CS2_FULL_RADIUS, "cs2", CS2_TILE_SIDE_METRES),
        (70.0, -100.0, CS2_FULL_RADIUS, "cs2", CS2_TILE_SIDE_METRES),
        (45.0, 10.0, 0, "cs1", CS1_TILE_SIDE_METRES),  # single-tile collapse
    ],
)
def test_should_produce_correct_side_length_when_resolving_center_extent(
    latitude: float,
    longitude: float,
    radius_tiles: int,
    target_id: str,
    tile_side: float,
) -> None:
    extent = CenterExtent(
        center=GeoPoint(longitude=longitude, latitude=latitude),
        radius_tiles=radius_tiles,
        target_id=target_id,
    )

    bounds = resolve_extent(extent)

    expected = _expected_side_metres(tile_side, radius_tiles)
    actual_width = _width_metres(bounds, latitude)
    actual_height = _height_metres(bounds)

    assert abs(actual_width - expected) / expected < WIDTH_TOLERANCE
    assert abs(actual_height - expected) / expected < WIDTH_TOLERANCE


def test_should_center_bounds_on_input_coordinate_when_resolving_center_extent() -> None:
    extent = CenterExtent(
        center=GeoPoint(longitude=-71.21, latitude=46.81),
        radius_tiles=CS1_FULL_RADIUS,
        target_id="cs1",
    )

    bounds = resolve_extent(extent)
    centroid_lon, centroid_lat = bounds.centroid

    assert centroid_lon == pytest.approx(-71.21, abs=1e-9)
    assert centroid_lat == pytest.approx(46.81, abs=1e-9)


def test_should_return_bounds_unchanged_when_resolving_bounds_extent() -> None:
    inner = GeoBounds(
        west=-1.0, south=10.0, east=1.0, north=12.0, crs=Projection.wgs84()
    )
    extent = BoundsExtent(bounds=inner)

    assert resolve_extent(extent) is inner


def test_should_reject_center_extent_when_resolution_crosses_antimeridian() -> None:
    extent = CenterExtent(
        center=GeoPoint(longitude=179.99, latitude=0.0),
        radius_tiles=CS1_FULL_RADIUS,
        target_id="cs1",
    )

    with pytest.raises(ExtentResolutionError, match="antimeridian"):
        resolve_extent(extent)


def test_should_reject_center_extent_when_center_latitude_exceeds_cap_north() -> None:
    with pytest.raises(ExtentResolutionError, match="latitude"):
        resolve_extent(
            CenterExtent(
                center=GeoPoint(longitude=0.0, latitude=85.5),
                radius_tiles=CS1_FULL_RADIUS,
                target_id="cs1",
            )
        )


def test_should_reject_center_extent_when_center_latitude_exceeds_cap_south() -> None:
    with pytest.raises(ExtentResolutionError, match="latitude"):
        resolve_extent(
            CenterExtent(
                center=GeoPoint(longitude=0.0, latitude=-85.5),
                radius_tiles=CS1_FULL_RADIUS,
                target_id="cs1",
            )
        )


def test_should_reject_center_extent_when_target_id_is_unknown() -> None:
    extent = CenterExtent(
        center=GeoPoint(longitude=0.0, latitude=0.0),
        radius_tiles=0,
        target_id="unknown-target",
    )

    with pytest.raises(ExtentResolutionError, match="Unknown target"):
        resolve_extent(extent)


def test_should_reject_center_extent_when_radius_exceeds_grid_max() -> None:
    # CS1 grid_dimension=9 → max radius is 4. Passing 5 must be rejected.
    extent = CenterExtent(
        center=GeoPoint(longitude=0.0, latitude=0.0),
        radius_tiles=5,
        target_id="cs1",
    )

    with pytest.raises(ExtentResolutionError, match="exceeds the maximum radius"):
        resolve_extent(extent)
