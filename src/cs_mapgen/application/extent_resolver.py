"""Resolve a user-intent `MapExtent` into a `ResolvedExtent`.

A `ResolvedExtent` carries three companion artefacts that the rest of the pipeline keeps
separate so the map stays north-up and axis-aligned in the working metric CRS:

- `target_bounds`: the axis-aligned square (or rectangle) **in the working CRS**. This is the
  exact area the final map covers. Heightmaps, water masks and quantised exports are all
  cropped to this rectangle. For `CenterExtent`, the side length is exactly
  `(2 * radius_tiles + 1) * tile_side_metres` — i.e. the user gets exactly the metric-square
  they asked for.
- `fetch_bounds`: the lat/lon envelope used to query external data providers (DEM, OSM).
  Derived by inverse-projecting the four corners of `target_bounds` back to WGS84 and taking
  the bounding lat/lon rectangle. This is necessarily slightly larger than `target_bounds`
  (it covers the rotated UTM square, plus a small safety pad), guaranteeing the reprojected
  DEM fully covers the target without nodata wedges on the edges.
- `working_crs`: the metric CRS picked for `target_bounds`. For v0.2 this is always a UTM
  zone (`pick_utm_projection`).

Why this design (see also `docs/adr/0006-axis-aligned-target-bounds.md` to be written):
The previous behaviour defined the extent in WGS84 and reprojected to UTM at fetch time. A
lat/lon rectangle reprojects to a non-axis-aligned UTM quadrilateral (meridian convergence
plus trapezoidal distortion), so the reprojected raster was rotated inside an axis-aligned
destination grid, leaving visible nodata wedges in the map corners — the "crooked map" bug.

Math note: we use `pyproj.Transformer` for the WGS84 ↔ working-CRS projections. This pulls
pyproj into the application layer; this is acceptable because pyproj is already a top-level
pipeline dependency (it underlies the `Reprojector` port) and centralising projection here
keeps the resolver responsibility single-piece. The `Reprojector` port is intentionally NOT
used here — that port operates on rasters/networks/water features, not point pairs, and the
resolver's pyproj usage is a few lines confined to one function.

Determinism: pyproj's `Transformer.transform` is bitwise deterministic for fixed inputs and a
fixed PROJ data version (pinned via the dev container).
"""

from __future__ import annotations

from dataclasses import dataclass

from cs_mapgen.domain.extent import (
    BoundsExtent,
    CenterExtent,
    InvalidExtentError,
    MapExtent,
)
from cs_mapgen.domain.geometry import (
    GeoBounds,
    InvalidBoundsError,
    Projection,
    pick_utm_projection,
)
from cs_mapgen.domain.target_specs import TargetSpec, get_target_spec

# Hard cap on absolute latitude. Above this UTM picks become unreliable and `pick_utm_projection`
# itself refuses. We cap earlier so the user sees an extent error before any projection logic is
# touched.
MAX_ABSOLUTE_LATITUDE_DEGREES = 85.0

# Hard cap on absolute longitude when checking antimeridian crossings.
ANTIMERIDIAN_LONGITUDE_DEGREES = 180.0

# The fetch envelope is the WGS84 bounding rectangle of `target_bounds` projected back to
# WGS84. We pad it by this fraction of the bbox span on each side so that GDAL's reprojection
# grid fully encloses the target square even after sub-pixel resampling shifts the edges.
FETCH_ENVELOPE_SAFETY_PAD_FRACTION = 0.002


class ExtentResolutionError(InvalidExtentError):
    """Raised when a `MapExtent` cannot be turned into a valid `ResolvedExtent`.

    Subclass of `InvalidExtentError` so callers that already handle the domain error type catch
    this one too; subclassing is preferred over a sibling type because resolution failures are
    semantically "this extent is invalid in this context".
    """


@dataclass(frozen=True, slots=True)
class ResolvedExtent:
    """A `MapExtent` resolved to the three artefacts the pipeline needs.

    The invariants this object enforces:
    - `target_bounds.crs == working_crs`
    - `fetch_bounds.crs == Projection.wgs84()`
    - `fetch_bounds` fully contains the projection of `target_bounds` back to WGS84 (plus a
      small safety margin).
    """

    target_bounds: GeoBounds
    fetch_bounds: GeoBounds
    working_crs: Projection

    def __post_init__(self) -> None:
        if self.target_bounds.crs.epsg != self.working_crs.epsg:
            raise ExtentResolutionError(
                "target_bounds CRS must equal working_crs "
                f"(target_bounds=EPSG:{self.target_bounds.crs.epsg}, "
                f"working_crs=EPSG:{self.working_crs.epsg})"
            )
        if self.fetch_bounds.crs.epsg != Projection.wgs84().epsg:
            raise ExtentResolutionError(
                f"fetch_bounds must be WGS84 (got EPSG:{self.fetch_bounds.crs.epsg})"
            )


def resolve_extent(extent: MapExtent) -> ResolvedExtent:
    """Turn any `MapExtent` shape into a `ResolvedExtent`.

    For `CenterExtent`: builds `target_bounds` as an exact UTM-axis-aligned square of side
    `(2*r+1) * tile_side_metres` around the projected centre. `fetch_bounds` is derived by
    inverse-projecting the four corners.

    For `BoundsExtent`: the user's lat/lon bbox becomes `fetch_bounds` directly; `target_bounds`
    is the largest UTM-axis-aligned rectangle inscribed inside the projected quadrilateral. The
    user gets data only inside the bbox they asked for — never outside — at the cost of a small
    loss near the corners where the quad's edges are not parallel to UTM axes.
    """
    if isinstance(extent, CenterExtent):
        return _resolve_center_extent(extent)
    if isinstance(extent, BoundsExtent):
        return _resolve_bounds_extent(extent)
    raise ExtentResolutionError(  # pragma: no cover — exhaustive over the tagged union
        f"Unsupported extent type: {type(extent).__name__}"
    )


def _resolve_center_extent(extent: CenterExtent) -> ResolvedExtent:
    spec = _get_spec_or_raise(extent.target_id)
    _validate_radius(extent.radius_tiles, spec)
    center = extent.center
    _validate_center_latitude(center.latitude)

    working_crs = _pick_working_crs_for_point(center.longitude, center.latitude)
    centre_x, centre_y = _project_point_wgs84_to(working_crs, center.longitude, center.latitude)

    side_metres = _side_length_metres(spec, extent.radius_tiles)
    half_side = side_metres / 2.0

    target_bounds = _build_bounds(
        west=centre_x - half_side,
        south=centre_y - half_side,
        east=centre_x + half_side,
        north=centre_y + half_side,
        crs=working_crs,
    )
    fetch_bounds = _derive_fetch_envelope(target_bounds)

    return ResolvedExtent(
        target_bounds=target_bounds,
        fetch_bounds=fetch_bounds,
        working_crs=working_crs,
    )


def _resolve_bounds_extent(extent: BoundsExtent) -> ResolvedExtent:
    fetch_bounds = extent.bounds
    if fetch_bounds.crs.epsg != Projection.wgs84().epsg:
        raise ExtentResolutionError(
            f"BoundsExtent requires WGS84 bounds (got EPSG:{fetch_bounds.crs.epsg})"
        )

    working_crs = pick_utm_projection(fetch_bounds)
    target_bounds = _inscribed_metric_rectangle(fetch_bounds, working_crs)
    return ResolvedExtent(
        target_bounds=target_bounds,
        fetch_bounds=fetch_bounds,
        working_crs=working_crs,
    )


def _inscribed_metric_rectangle(
    fetch_bounds: GeoBounds,
    working_crs: Projection,
) -> GeoBounds:
    """Project the 4 corners of `fetch_bounds` to `working_crs` and return the largest
    axis-aligned rectangle inscribed inside the resulting quadrilateral.

    "Inscribed" means each edge of the rectangle is at the most-restrictive of the two
    candidate boundaries on that side (e.g. `west = max(x_NW, x_SW)`). For city-sized bboxes
    this approximation is sub-pixel — the projected edges are nearly straight at that scale.
    """
    nw = _project_point_wgs84_to(working_crs, fetch_bounds.west, fetch_bounds.north)
    ne = _project_point_wgs84_to(working_crs, fetch_bounds.east, fetch_bounds.north)
    sw = _project_point_wgs84_to(working_crs, fetch_bounds.west, fetch_bounds.south)
    se = _project_point_wgs84_to(working_crs, fetch_bounds.east, fetch_bounds.south)

    west = max(nw[0], sw[0])
    east = min(ne[0], se[0])
    south = max(sw[1], se[1])
    north = min(nw[1], ne[1])
    if west >= east or south >= north:
        raise ExtentResolutionError(
            "Bounds extent collapses to an empty rectangle after projection to the working CRS. "
            "The input lat/lon bbox is too small or too skewed."
        )
    return _build_bounds(west=west, south=south, east=east, north=north, crs=working_crs)


def _derive_fetch_envelope(target_bounds: GeoBounds) -> GeoBounds:
    """Inverse-project the 4 corners of `target_bounds` to WGS84 and return the bounding box.

    We add a small fractional safety pad so that GDAL's destination grid (computed by
    `calculate_default_transform`) fully covers `target_bounds` even after sub-pixel
    resampling shifts.

    Antimeridian and pole overflows are detected here on the raw lon/lat values and surfaced
    as `ExtentResolutionError` so the user sees a clear "antimeridian / pole" message rather
    than a generic GeoBounds-range error.
    """
    nw = _project_point_to_wgs84(target_bounds.crs, target_bounds.west, target_bounds.north)
    ne = _project_point_to_wgs84(target_bounds.crs, target_bounds.east, target_bounds.north)
    sw = _project_point_to_wgs84(target_bounds.crs, target_bounds.west, target_bounds.south)
    se = _project_point_to_wgs84(target_bounds.crs, target_bounds.east, target_bounds.south)

    lons = (nw[0], ne[0], sw[0], se[0])
    lats = (nw[1], ne[1], sw[1], se[1])
    west, east = min(lons), max(lons)
    south, north = min(lats), max(lats)

    pad_lon = (east - west) * FETCH_ENVELOPE_SAFETY_PAD_FRACTION
    pad_lat = (north - south) * FETCH_ENVELOPE_SAFETY_PAD_FRACTION
    padded_west = west - pad_lon
    padded_east = east + pad_lon
    padded_south = south - pad_lat
    padded_north = north + pad_lat
    _validate_no_antimeridian_crossing(padded_west, padded_east)
    _validate_no_pole_overflow(padded_south, padded_north)
    return _build_bounds(
        west=padded_west,
        south=padded_south,
        east=padded_east,
        north=padded_north,
        crs=Projection.wgs84(),
    )


def _pick_working_crs_for_point(longitude: float, latitude: float) -> Projection:
    # `pick_utm_projection` operates on `GeoBounds`. Build a degenerate bbox at the point and
    # let the existing zone-selection logic do its job. The degenerate bbox is never used past
    # this call, so we accept it failing the GeoBounds invariants gracefully — picking a small
    # epsilon avoids the zero-area validation.
    epsilon = 1e-6
    try:
        synthetic = GeoBounds(
            west=longitude - epsilon,
            south=latitude - epsilon,
            east=longitude + epsilon,
            north=latitude + epsilon,
            crs=Projection.wgs84(),
        )
    except InvalidBoundsError as error:
        raise ExtentResolutionError(str(error)) from error
    return pick_utm_projection(synthetic)


def _project_point_wgs84_to(
    target: Projection,
    longitude: float,
    latitude: float,
) -> tuple[float, float]:
    # Local import: keeps pyproj off the import-time critical path.
    from pyproj import Transformer  # noqa: PLC0415

    transformer = Transformer.from_crs(
        "EPSG:4326",
        f"EPSG:{target.epsg}",
        always_xy=True,
    )
    x, y = transformer.transform(longitude, latitude)
    return float(x), float(y)


def _project_point_to_wgs84(
    source: Projection,
    x: float,
    y: float,
) -> tuple[float, float]:
    # Local import: keeps pyproj off the import-time critical path.
    from pyproj import Transformer  # noqa: PLC0415

    transformer = Transformer.from_crs(
        f"EPSG:{source.epsg}",
        "EPSG:4326",
        always_xy=True,
    )
    lon, lat = transformer.transform(x, y)
    return float(lon), float(lat)


def _build_bounds(
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    crs: Projection,
) -> GeoBounds:
    try:
        return GeoBounds(west=west, south=south, east=east, north=north, crs=crs)
    except InvalidBoundsError as error:
        raise ExtentResolutionError(str(error)) from error


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


def _validate_no_antimeridian_crossing(west: float, east: float) -> None:
    # We refuse extents whose computed west/east leak past ±180°. v0.2 working CRS is UTM
    # and UTM is undefined across the antimeridian; rejecting at the resolver gives the user a
    # clear, early error instead of a confusing one deep in reprojection.
    if west < -ANTIMERIDIAN_LONGITUDE_DEGREES or east > ANTIMERIDIAN_LONGITUDE_DEGREES:
        raise ExtentResolutionError(
            f"Center extent crosses the antimeridian (resolved west={west}, east={east}). "
            "Antimeridian-crossing bboxes are not supported in v0.2."
        )


def _validate_no_pole_overflow(south: float, north: float) -> None:
    if south < -90.0 or north > 90.0:
        raise ExtentResolutionError(
            f"Center extent overflows a pole (resolved south={south}, north={north}). "
            "Reduce radius_tiles or choose a centre further from the pole."
        )
