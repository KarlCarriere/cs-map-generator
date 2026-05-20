"""Unit tests for `resolve_extent`.

The resolver now returns a `ResolvedExtent` carrying:

- `target_bounds` (working_crs): exact axis-aligned UTM square / rectangle.
- `fetch_bounds` (WGS84): lat/lon envelope guaranteed to cover `target_bounds`.
- `working_crs`: the picked UTM zone.

These tests assert:

- For `CenterExtent`, `target_bounds` is exactly square with the requested metric side.
- `fetch_bounds` always covers `target_bounds` after projecting target corners back to WGS84.
- The previous boundary rejections (antimeridian, latitude cap, unknown target) still apply.
"""

from __future__ import annotations

import pytest

from cs_mapgen.application.extent_resolver import (
    ExtentResolutionError,
    resolve_extent,
)
from cs_mapgen.domain.extent import BoundsExtent, CenterExtent, GeoPoint
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.target_specs import (
    CS1_TILE_SIDE_METRES,
    CS2_TILE_SIDE_METRES,
)

WGS84 = Projection.wgs84()

# Sub-metre tolerance on the metric square side length.
SIDE_TOLERANCE_METRES = 1e-6

CS1_FULL_RADIUS = 4
CS2_FULL_RADIUS = 10


def _expected_side_metres(tile_side_metres: float, radius_tiles: int) -> float:
    return (2 * radius_tiles + 1) * tile_side_metres


@pytest.mark.parametrize(
    ("latitude", "longitude", "radius_tiles", "target_id", "tile_side"),
    [
        (0.0, 0.0, CS1_FULL_RADIUS, "cs1", CS1_TILE_SIDE_METRES),  # equator
        (45.0, 10.0, CS1_FULL_RADIUS, "cs1", CS1_TILE_SIDE_METRES),  # mid-latitude
        (70.0, -100.0, CS1_FULL_RADIUS, "cs1", CS1_TILE_SIDE_METRES),  # high-latitude
        (46.81, -71.21, CS1_FULL_RADIUS, "cs1", CS1_TILE_SIDE_METRES),  # Quebec (the bug)
        (0.0, 0.0, CS2_FULL_RADIUS, "cs2", CS2_TILE_SIDE_METRES),
        (45.0, 10.0, CS2_FULL_RADIUS, "cs2", CS2_TILE_SIDE_METRES),
        (70.0, -100.0, CS2_FULL_RADIUS, "cs2", CS2_TILE_SIDE_METRES),
        (45.0, 10.0, 0, "cs1", CS1_TILE_SIDE_METRES),  # single-tile collapse
    ],
)
def test_should_produce_target_bounds_with_exact_metric_side_when_resolving_center_extent(
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

    resolved = resolve_extent(extent)

    expected = _expected_side_metres(tile_side, radius_tiles)
    width = resolved.target_bounds.east - resolved.target_bounds.west
    height = resolved.target_bounds.north - resolved.target_bounds.south

    assert width == pytest.approx(expected, abs=SIDE_TOLERANCE_METRES)
    assert height == pytest.approx(expected, abs=SIDE_TOLERANCE_METRES)


def test_should_pick_utm_zone_19n_when_resolving_quebec_center() -> None:
    extent = CenterExtent(
        center=GeoPoint(longitude=-71.21, latitude=46.81),
        radius_tiles=CS1_FULL_RADIUS,
        target_id="cs1",
    )

    resolved = resolve_extent(extent)

    # Quebec at lon -71.21 falls into UTM zone 19 (northern hemisphere → EPSG 32619).
    assert resolved.working_crs.epsg == 32619
    assert resolved.target_bounds.crs.epsg == 32619
    assert resolved.fetch_bounds.crs.epsg == 4326


def test_should_center_target_bounds_on_projected_center_when_resolving_center_extent() -> None:
    extent = CenterExtent(
        center=GeoPoint(longitude=-71.21, latitude=46.81),
        radius_tiles=CS1_FULL_RADIUS,
        target_id="cs1",
    )

    resolved = resolve_extent(extent)
    target_centroid_x, target_centroid_y = resolved.target_bounds.centroid

    # The centroid of target_bounds should equal the projected centre point.
    from pyproj import Transformer  # noqa: PLC0415

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32619", always_xy=True)
    expected_x, expected_y = transformer.transform(-71.21, 46.81)
    assert target_centroid_x == pytest.approx(expected_x, abs=1e-6)
    assert target_centroid_y == pytest.approx(expected_y, abs=1e-6)


def test_should_envelope_target_bounds_when_deriving_fetch_bounds() -> None:
    """`fetch_bounds` must cover the WGS84 projection of every corner of target_bounds."""
    extent = CenterExtent(
        center=GeoPoint(longitude=-71.21, latitude=46.81),
        radius_tiles=CS1_FULL_RADIUS,
        target_id="cs1",
    )

    resolved = resolve_extent(extent)

    from pyproj import Transformer  # noqa: PLC0415

    to_wgs84 = Transformer.from_crs(
        f"EPSG:{resolved.working_crs.epsg}", "EPSG:4326", always_xy=True
    )
    corners = [
        (resolved.target_bounds.west, resolved.target_bounds.south),
        (resolved.target_bounds.east, resolved.target_bounds.south),
        (resolved.target_bounds.east, resolved.target_bounds.north),
        (resolved.target_bounds.west, resolved.target_bounds.north),
    ]
    for x, y in corners:
        lon, lat = to_wgs84.transform(x, y)
        assert resolved.fetch_bounds.west <= lon <= resolved.fetch_bounds.east
        assert resolved.fetch_bounds.south <= lat <= resolved.fetch_bounds.north


def test_should_preserve_user_bbox_as_fetch_bounds_when_resolving_bounds_extent() -> None:
    inner = GeoBounds(west=-1.0, south=10.0, east=1.0, north=12.0, crs=WGS84)
    extent = BoundsExtent(bounds=inner)

    resolved = resolve_extent(extent)

    assert resolved.fetch_bounds is inner
    # target_bounds is in working_crs (UTM), inscribed inside the projected fetch_bounds quad.
    assert resolved.target_bounds.crs.epsg == resolved.working_crs.epsg
    assert resolved.target_bounds.crs.epsg != WGS84.epsg


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
