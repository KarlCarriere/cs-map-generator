"""Resolve a user-intent `MapExtent` into a concrete WGS84 `GeoBounds`.

This is the only place that knows about both the per-game tile-grid spec and the lat/lon math
needed to expand a centre coordinate into a bounding box. The rest of the pipeline keeps
taking a plain `GeoBounds`, so adding new input shapes (center+radius today, GPS+heading
later) means adding new branches here and nowhere else.

Math choice (see `docs/adr/0003-center-coordinate-input.md`):
We use a local equirectangular approximation around the centre latitude rather than a
pyproj geodesic. CS-sized maps are at most ~17.3 km (CS1) or ~13.1 km (CS2) per side, and
the equirectangular approximation's error over that span is well under 0.1% of one tile at
every latitude we accept. It is also pure Python (no pyproj dep in the application layer),
deterministic, and trivially auditable. Geodesic precision is overkill at this scale.

Determinism: pure function over its inputs. No I/O, no globals, no RNG.
"""

from __future__ import annotations

from math import cos, radians

from cs_mapgen.domain.extent import (
    BoundsExtent,
    CenterExtent,
    InvalidExtentError,
    MapExtent,
)
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.target_specs import TargetSpec, get_target_spec

# Earth radius used for the equirectangular conversion. WGS84 mean radius in metres.
# Picking the mean (rather than equatorial) keeps mid-latitude error symmetric.
EARTH_RADIUS_METRES = 6_371_008.8

# Hard cap on absolute latitude. Above this the equirectangular `cos(lat)` term becomes
# numerically unstable AND we are already outside the v0.1 UTM-only working CRS scope. The
# domain-level `pick_utm_projection` already refuses centroids above 84° N / below 80° S, but
# we cap earlier so the user sees an extent error before any projection logic is touched.
MAX_ABSOLUTE_LATITUDE_DEGREES = 85.0

# Hard cap on absolute longitude when checking antimeridian crossings.
ANTIMERIDIAN_LONGITUDE_DEGREES = 180.0


class ExtentResolutionError(InvalidExtentError):
    """Raised when a `MapExtent` cannot be turned into a valid WGS84 `GeoBounds`.

    Subclass of `InvalidExtentError` so callers that already handle the domain error type catch
    this one too; subclassing is preferred over a sibling type because resolution failures are
    semantically "this extent is invalid in this context".
    """


def resolve_extent(extent: MapExtent) -> GeoBounds:
    """Turn any `MapExtent` shape into a concrete WGS84 `GeoBounds`.

    For `BoundsExtent`, this is essentially a passthrough (the bounds already are a GeoBounds).
    For `CenterExtent`, we look up the per-game `TargetSpec`, compute the side length in metres
    from the tile geometry, and convert that to a lat/lon rectangle using a local
    equirectangular approximation around the centre latitude.
    """
    # `isinstance` rather than `match` here because the tagged-union members carry an explicit
    # `kind` literal: positional pattern matching would silently bind the wrong field if the
    # field order ever shifted. `isinstance` is also cheaper and easier for static analysers.
    if isinstance(extent, BoundsExtent):
        return extent.bounds
    if isinstance(extent, CenterExtent):
        return _resolve_center_extent(extent)
    raise ExtentResolutionError(  # pragma: no cover — exhaustive over the tagged union
        f"Unsupported extent type: {type(extent).__name__}"
    )


def _resolve_center_extent(extent: CenterExtent) -> GeoBounds:
    spec = _get_spec_or_raise(extent.target_id)
    _validate_radius(extent.radius_tiles, spec)
    center = extent.center
    _validate_center_latitude(center.latitude)

    side_metres = _side_length_metres(spec, extent.radius_tiles)
    half_side_metres = side_metres / 2.0

    half_height_degrees = _metres_to_latitude_degrees(half_side_metres)
    half_width_degrees = _metres_to_longitude_degrees(half_side_metres, center.latitude)

    south = center.latitude - half_height_degrees
    north = center.latitude + half_height_degrees
    west = center.longitude - half_width_degrees
    east = center.longitude + half_width_degrees

    _validate_no_antimeridian_crossing(west, east)
    _validate_no_pole_overflow(south, north)

    return GeoBounds(west=west, south=south, east=east, north=north, crs=Projection.wgs84())


def _get_spec_or_raise(target_id: str) -> TargetSpec:
    try:
        return get_target_spec(target_id)
    except KeyError as error:
        # KeyError subclass propagates as ExtentResolutionError for a single typed error surface.
        raise ExtentResolutionError(str(error)) from error


def _validate_radius(radius_tiles: int, spec: TargetSpec) -> None:
    if radius_tiles > spec.max_radius_tiles:
        raise ExtentResolutionError(
            f"radius_tiles {radius_tiles} exceeds the maximum radius {spec.max_radius_tiles} "
            f"for target {spec.target_id!r} (grid_dimension={spec.grid_dimension})"
        )


def _validate_center_latitude(latitude: float) -> None:
    if abs(latitude) > MAX_ABSOLUTE_LATITUDE_DEGREES:
        raise ExtentResolutionError(
            f"center latitude {latitude} exceeds the v0.1 absolute-latitude cap "
            f"of {MAX_ABSOLUTE_LATITUDE_DEGREES}° (UTM is undefined near the poles)"
        )


def _side_length_metres(spec: TargetSpec, radius_tiles: int) -> float:
    # The extent covers the centre tile plus `radius_tiles` tiles in every cardinal direction,
    # so the full side spans `2 * radius_tiles + 1` tiles. `radius_tiles=0` collapses to a
    # single-tile map; we allow it (useful for tiny test fixtures) but the resolver still
    # produces a valid non-zero-area bbox.
    return (2.0 * radius_tiles + 1.0) * spec.tile_side_metres


def _metres_to_latitude_degrees(distance_metres: float) -> float:
    # One degree of latitude is essentially constant: 2 * pi * R / 360.
    metres_per_degree = (2.0 * 3.141592653589793 * EARTH_RADIUS_METRES) / 360.0
    return distance_metres / metres_per_degree


def _metres_to_longitude_degrees(distance_metres: float, latitude_degrees: float) -> float:
    # One degree of longitude shrinks as `cos(latitude)` toward the poles. This is the entire
    # reason we cannot just scale lon-deltas by the same factor as lat-deltas.
    base_metres_per_degree = (2.0 * 3.141592653589793 * EARTH_RADIUS_METRES) / 360.0
    cosine = cos(radians(latitude_degrees))
    if cosine <= 0.0:
        # cos(85°) ≈ 0.087 so we never hit this in practice given MAX_ABSOLUTE_LATITUDE_DEGREES,
        # but be defensive — division by zero or negative cosine would produce a wrap.
        raise ExtentResolutionError(
            f"Latitude {latitude_degrees} is too close to a pole to resolve a longitude span"
        )
    metres_per_degree = base_metres_per_degree * cosine
    return distance_metres / metres_per_degree


def _validate_no_antimeridian_crossing(west: float, east: float) -> None:
    # We refuse extents whose computed west/east leak past ±180°. v0.1 working CRS is UTM
    # and UTM is undefined across the antimeridian; rejecting at the resolver gives the user a
    # clear, early error instead of a confusing one deep in reprojection.
    if west < -ANTIMERIDIAN_LONGITUDE_DEGREES or east > ANTIMERIDIAN_LONGITUDE_DEGREES:
        raise ExtentResolutionError(
            f"Center extent crosses the antimeridian (resolved west={west}, east={east}). "
            "Antimeridian-crossing bboxes are not supported in v0.1."
        )


def _validate_no_pole_overflow(south: float, north: float) -> None:
    if south < -90.0 or north > 90.0:
        raise ExtentResolutionError(
            f"Center extent overflows a pole (resolved south={south}, north={north}). "
            "Reduce radius_tiles or choose a centre further from the pole."
        )
