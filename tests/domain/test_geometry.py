"""Unit tests for `GeoBounds` and `Projection`."""

from __future__ import annotations

import pytest

from cs_mapgen.domain.geometry import (
    GeoBounds,
    InvalidBoundsError,
    Projection,
    pick_utm_projection,
)


def test_should_construct_valid_wgs84_bounds_when_input_is_well_formed() -> None:
    bounds = GeoBounds(west=-1.0, south=10.0, east=2.0, north=20.0, crs=Projection.wgs84())

    assert bounds.as_tuple() == (-1.0, 10.0, 2.0, 20.0)
    assert bounds.centroid == (0.5, 15.0)
    assert bounds.width == pytest.approx(3.0)
    assert bounds.height == pytest.approx(10.0)


def test_should_reject_bounds_when_east_is_not_greater_than_west() -> None:
    with pytest.raises(InvalidBoundsError):
        GeoBounds(west=2.0, south=0.0, east=2.0, north=1.0, crs=Projection.wgs84())


def test_should_reject_bounds_when_north_is_not_greater_than_south() -> None:
    with pytest.raises(InvalidBoundsError):
        GeoBounds(west=0.0, south=10.0, east=1.0, north=5.0, crs=Projection.wgs84())


def test_should_reject_bounds_when_longitude_exceeds_wgs84_range() -> None:
    with pytest.raises(InvalidBoundsError):
        GeoBounds(west=-200.0, south=0.0, east=10.0, north=10.0, crs=Projection.wgs84())


def test_should_pick_northern_utm_zone_when_centroid_is_in_north_hemisphere() -> None:
    paris_bbox = GeoBounds(
        west=2.2, south=48.8, east=2.5, north=49.0, crs=Projection.wgs84()
    )

    projection = pick_utm_projection(paris_bbox)

    # Paris is in UTM zone 31N -> EPSG:32631
    assert projection.epsg == 32631


def test_should_pick_southern_utm_zone_when_centroid_is_in_south_hemisphere() -> None:
    sydney_bbox = GeoBounds(
        west=151.0, south=-34.0, east=151.5, north=-33.5, crs=Projection.wgs84()
    )

    projection = pick_utm_projection(sydney_bbox)

    # Sydney is in UTM zone 56S -> EPSG:32756
    assert projection.epsg == 32756


def test_should_reject_polar_bounds_when_picking_utm_zone() -> None:
    arctic_bbox = GeoBounds(
        west=0.0, south=85.0, east=1.0, north=86.0, crs=Projection.wgs84()
    )

    with pytest.raises(InvalidBoundsError):
        pick_utm_projection(arctic_bbox)
