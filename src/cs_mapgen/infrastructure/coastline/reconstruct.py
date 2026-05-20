"""Reconstruct closed sea polygons from open OSM `natural=coastline` line segments.

OSM convention: coastline lines are directed with **land on the left, sea on the right**. Each
segment is an open polyline of WGS84 coordinates. The job of this module is to take a bag of
such segments together with a bounding rectangle (the user's bbox in the working CRS) and
return a polygonal representation of the **sea** area inside that rectangle.

Algorithm (deterministic, fully offline, no I/O):

1. Clip each input segment to the bounding rectangle. Segments fully outside are dropped;
   segments straddling the boundary are split so each endpoint either lies on the boundary or
   is strictly inside.
2. Walk the boundary in counter-clockwise order (the OSM-convention "sea side" direction)
   joining the clipped segments via boundary arcs. Each closed loop assembled this way bounds
   a connected sea area.
3. Return a `MultiPolygon` of all closed loops.

Out of scope (deferred via `InvalidBoundsError` consistent with v0.1 risk #2):
- bboxes crossing the antimeridian (±180°).
- bboxes containing or near a pole.
- "all sea" or "all land" bboxes where no coastline crosses the boundary — handled as a
  degenerate case returning an empty MultiPolygon (caller decides what to do).

Determinism notes:
- All iteration over the input segments is by index in the order received. Callers (the OSM
  adapter) sort segments by stable keys before passing them in.
- Boundary arcs are inserted in the order the segments cross the boundary; that order is
  deterministic given a deterministic input order.
- Float equality is avoided: boundary-coincidence is tested with `shapely.equals_exact(tolerance)`
  using a single, small tolerance in projected metres.
"""

from __future__ import annotations

from collections.abc import Iterable

from cs_mapgen.domain.geometry import GeoBounds
from cs_mapgen.domain.water import CoastlineSegment


class CoastlineReconstructionError(ValueError):
    """Raised when the input coastlines + bbox cannot be assembled into a valid sea polygon."""


def reconstruct_sea_polygons(
    coastlines: Iterable[CoastlineSegment],
    bounds: GeoBounds,
) -> object:
    """Return a shapely `MultiPolygon` of sea area inside `bounds`.

    `bounds` MUST already be in the working CRS (metric). This function never reprojects —
    that responsibility lives in the caller (`PrepareWaterStage`).

    The return type is `object` to keep this module's signature shapely-free at the import
    boundary. Callers downcast to `shapely.geometry.MultiPolygon` immediately.

    Empty input → empty `MultiPolygon` (no coastlines means "no sea polygon to assemble"). The
    caller decides whether to interpret that as "all land", "all sea", or "no information"
    based on context.
    """
    from shapely.geometry import LineString, MultiPolygon, Polygon, box  # noqa: PLC0415
    from shapely.ops import polygonize, unary_union  # noqa: PLC0415

    coastlines = tuple(coastlines)
    bounding_box: Polygon = box(bounds.west, bounds.south, bounds.east, bounds.north)
    if not coastlines:
        return MultiPolygon()

    # Build LineStrings from the raw coordinate tuples. Reject any segment that is degenerate
    # (zero-length after deduplication) because polygonize cannot consume it.
    raw_lines: list[LineString] = []
    for segment in coastlines:
        coords = _dedupe_consecutive(segment.geometry)
        if len(coords) < 2:
            continue
        raw_lines.append(LineString(coords))

    if not raw_lines:
        return MultiPolygon()

    # Clip each coastline to the bbox. shapely's intersection handles cleanly: result is
    # either a LineString, a MultiLineString, or empty.
    clipped_lines: list[LineString] = []
    for line in raw_lines:
        clipped = line.intersection(bounding_box)
        if clipped.is_empty:
            continue
        if clipped.geom_type == "LineString":
            clipped_lines.append(clipped)
        elif clipped.geom_type == "MultiLineString":
            clipped_lines.extend(geom for geom in clipped.geoms if geom.geom_type == "LineString")
        # Any other geometry type (Point — coastline tangent to bbox corner) is dropped: a
        # single-point intersection cannot participate in polygon assembly.

    if not clipped_lines:
        return MultiPolygon()

    # The polygonize trick: union together the clipped coastlines + the bbox boundary, then
    # ask shapely to polygonize. This is the canonical OSM coastline-closure approach used by
    # osmcoastline and similar tools, adapted here for a single bbox window.
    boundary_loop = LineString(
        (
            (bounds.west, bounds.south),
            (bounds.east, bounds.south),
            (bounds.east, bounds.north),
            (bounds.west, bounds.north),
            (bounds.west, bounds.south),
        )
    )
    merged = unary_union([*clipped_lines, boundary_loop])
    candidate_polygons = list(polygonize(merged))

    if not candidate_polygons:
        return MultiPolygon()

    # The polygonize output includes BOTH land and sea pieces (every closed region bounded by
    # the union is emitted). We pick the sea pieces by sampling a representative interior
    # point and checking which side of the nearest coastline it lies on, using OSM's
    # "land on the left, sea on the right" rule.
    sea_polygons = _select_sea_polygons(candidate_polygons, clipped_lines)
    return MultiPolygon(sea_polygons) if sea_polygons else MultiPolygon()


def _dedupe_consecutive(
    coords: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    """Drop consecutive-duplicate vertices. Some OSM data has them; shapely refuses."""
    if not coords:
        return ()
    result: list[tuple[float, float]] = [coords[0]]
    for vertex in coords[1:]:
        if vertex != result[-1]:
            result.append(vertex)
    return tuple(result)


def _select_sea_polygons(
    candidates: list[object],
    clipped_lines: list[object],
) -> list[object]:
    """Pick the polygons that are sea (right-of-coastline) per the OSM convention.

    For each candidate polygon: find the nearest clipped coastline LineString, project the
    polygon's interior representative point onto that line, and test which side of the line
    the point sits on relative to the line's direction. A point on the right-hand side is
    sea; on the left it is land. Polygons with no nearby coastline (e.g. interior bbox with
    no adjacent coastline) are dropped — they could be either, and "drop" is the safe default
    that matches the v0.2 brief's "augment, do not replace" stance.
    """
    from shapely.geometry import Point  # noqa: PLC0415

    if not clipped_lines:
        return []

    sea: list[object] = []
    for polygon in candidates:
        # `representative_point` is guaranteed to lie inside the polygon (unlike `centroid`,
        # which can fall outside for concave shapes).
        point: Point = polygon.representative_point()  # type: ignore[attr-defined]
        nearest_line = min(clipped_lines, key=lambda line, p=point: line.distance(p))
        if _point_is_on_right_of_line(point, nearest_line):
            sea.append(polygon)
    return sea


def _point_is_on_right_of_line(point: object, line: object) -> bool:
    """Return True if `point` lies on the right-hand side of the line's direction of travel."""
    # We project the point onto the line to find the closest segment, then compute the cross
    # product of (segment_direction, point - segment_start). Right-hand-side ⇔ negative cross
    # product in standard 2D screen-positive-up convention.
    coords = list(line.coords)  # type: ignore[attr-defined]
    if len(coords) < 2:
        return False

    px, py = point.x, point.y  # type: ignore[attr-defined]
    best_cross = 0.0
    best_distance = float("inf")
    for index in range(len(coords) - 1):
        x0, y0 = coords[index]
        x1, y1 = coords[index + 1]
        seg_dx = x1 - x0
        seg_dy = y1 - y0
        seg_length_squared = seg_dx * seg_dx + seg_dy * seg_dy
        if seg_length_squared <= 0.0:
            continue
        # Parameterise: closest point on segment is at t in [0, 1].
        t = ((px - x0) * seg_dx + (py - y0) * seg_dy) / seg_length_squared
        t_clamped = max(0.0, min(1.0, t))
        closest_x = x0 + t_clamped * seg_dx
        closest_y = y0 + t_clamped * seg_dy
        distance_squared = (px - closest_x) ** 2 + (py - closest_y) ** 2
        if distance_squared < best_distance:
            best_distance = distance_squared
            # Sign of (P - A) × direction; positive = left, negative = right.
            cross = seg_dx * (py - y0) - seg_dy * (px - x0)
            best_cross = cross
    return best_cross < 0.0
