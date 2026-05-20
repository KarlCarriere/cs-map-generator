"""Prepare water: reproject + rasterise OSM water features into a heightmap-aligned mask.

This stage runs after `ConditionTerrainStage` and before `QuantizeHeightmapStage`. It consumes:

- The hydrologically-conditioned float terrain (`PreparedTerrain`) — used purely for its grid
  shape and affine transform. The elevation values are NOT modified by this stage; carving
  happens at quantise time using the mask we produce here.
- The raw, WGS84 water features ingested upstream — reprojected here to the working CRS, then
  rasterised onto the terrain grid.

Outputs:

- A `PrepareWaterResult` carrying the prepared terrain unchanged, the road network forwarded,
  and a `WaterMask` aligned to the terrain grid.

CRS expectations:
- Input water features are in `features.crs` (WGS84 from `OSMnxWaterSource`).
- Output mask is in the working CRS, matching `prepared_terrain.transform`.

Determinism:
- Reprojection is delegated to the injected `Reprojector` (pyproj is bitwise deterministic).
- Rasterisation is delegated to `rasterio.features.rasterize`, which is deterministic for a
  fixed shape order. Polygons and waterways are iterated in their input order — the OSM
  adapter sorts them by stable keys (osmid) at ingest time.
- River-buffering uses `shapely.geometry.LineString.buffer(width / 2)`, which is deterministic.

Algorithm choices (documented in ADR 0005):
- Coastlines → reconstructed into a sea MultiPolygon (closed against the bbox edges), then
  burned as a water polygon.
- `natural=water` polygons → burned directly with `all_touched=True` (any pixel intersected
  by the polygon edge counts as water — slightly over-paints, but ensures we never lose
  one-pixel-wide shorelines).
- `waterway=*` lines → buffered by `WATERWAY_WIDTH_METRES[class] / 2` then burned. Unknown
  classes are skipped.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cs_mapgen.application.ports import Reprojector
from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.condition_terrain import ConditionTerrainResult
from cs_mapgen.application.stages.prepare_terrain import PreparedTerrain
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.water import (
    WATERWAY_WIDTH_METRES,
    CoastlineSegment,
    WaterFeatures,
    WaterMask,
    WaterPolygon,
    Waterway,
)

# Type alias: a coastline reconstructor turns (segments, bounds) into a shapely MultiPolygon.
# The application layer treats the return value as `object` (no shapely import here); the only
# consumer is the rasteriser below, which downcasts at the boundary.
CoastlineReconstructor = Callable[[Iterable[CoastlineSegment], GeoBounds], object]


@dataclass(frozen=True, slots=True)
class PrepareWaterResult:
    prepared_terrain: PreparedTerrain
    road_network: RoadNetwork
    water_mask: WaterMask


class PrepareWaterStage:
    """Reproject + rasterise water features onto the terrain grid.

    `waterway_widths_metres` overrides the per-class buffer widths used to dilate
    `waterway=*` lines into the mask. Classes not present in the mapping are skipped.
    """

    name = "prepare_water"

    def __init__(
        self,
        reprojector: Reprojector,
        coastline_reconstructor: CoastlineReconstructor | None = None,
        waterway_widths_metres: dict[str, float] | None = None,
    ) -> None:
        self._reprojector = reprojector
        # Default to the infrastructure implementation via lazy import — keeps the application
        # package free of an eager infrastructure import at module-load time, but still gives
        # callers a sensible default they do not have to wire by hand.
        self._coastline_reconstructor = coastline_reconstructor or _default_coastline_reconstructor
        # Copy the default mapping so a caller mutating their dict later cannot influence this
        # stage's behaviour mid-run.
        self._waterway_widths_metres = dict(
            waterway_widths_metres if waterway_widths_metres is not None else WATERWAY_WIDTH_METRES
        )

    def run(
        self,
        inputs: ConditionTerrainResult,
        context: StageContext,
    ) -> PrepareWaterResult:
        prepared = inputs.prepared_terrain
        features_working_crs = self._reprojector.reproject_water_features(
            inputs.water_features, context.working_crs
        )

        # Coastline reconstruction expects bounds already in the working CRS — convert the
        # user-facing WGS84 bounds via the terrain transform extent.
        working_bounds = _bounds_from_transform(
            prepared.transform, prepared.elevation.shape, context.working_crs
        )
        sea_polygon = self._coastline_reconstructor(features_working_crs.coastlines, working_bounds)

        mask_array = _rasterise_water_features(
            polygons=features_working_crs.polygons,
            waterways=features_working_crs.waterways,
            sea_polygon=sea_polygon,
            waterway_widths_metres=self._waterway_widths_metres,
            target_shape=prepared.elevation.shape,
            target_transform=prepared.transform,
        )

        # Sanity log — useful in development to confirm the mask actually has water in it for
        # bboxes that should. We log fraction to two decimals; the actual value is binary.
        water_mask = WaterMask(
            mask=mask_array,
            transform=prepared.transform,
            crs=context.working_crs,
        )
        context.logger.info(
            "water.rasterised",
            extra={
                "coverage_fraction": round(water_mask.coverage_fraction, 4),
                "polygon_count": len(features_working_crs.polygons),
                "waterway_count": len(features_working_crs.waterways),
                "coastline_count": len(features_working_crs.coastlines),
            },
        )

        return PrepareWaterResult(
            prepared_terrain=prepared,
            road_network=inputs.road_network,
            water_mask=water_mask,
        )


def _bounds_from_transform(
    transform: tuple[float, float, float, float, float, float],
    shape: tuple[int, int],
    working_crs: Projection,
) -> GeoBounds:
    a, b, c, d, e, f = transform
    del b, d  # rotation terms unused on axis-aligned grids
    rows, cols = shape
    west = c
    north = f
    east = c + a * cols
    south = f + e * rows
    if east <= west or north <= south:
        # `GeoBounds` rejects degenerate or inverted bboxes. Defensive — `prepare_terrain` would
        # already have asserted a valid grid, so this should never trip.
        raise ValueError(
            f"Degenerate working bounds reconstructed from transform: "
            f"west={west}, south={south}, east={east}, north={north}"
        )
    # NOTE: `working_crs` carries the actual UTM/equal-area CRS picked at ingest. The
    # WGS84 latitude-range check in `GeoBounds.__post_init__` is skipped for non-WGS84 CRSes.
    return GeoBounds(west=west, south=south, east=east, north=north, crs=working_crs)


def _rasterise_water_features(
    *,
    polygons: tuple[WaterPolygon, ...],
    waterways: tuple[Waterway, ...],
    sea_polygon: object,
    waterway_widths_metres: dict[str, float],
    target_shape: tuple[int, int],
    target_transform: tuple[float, float, float, float, float, float],
) -> NDArray[np.bool_]:
    """Rasterise polygons + buffered waterways + sea polygon into one boolean mask.

    Returns a `bool` 2D array of shape `target_shape`.
    """
    # Local imports keep the heavy GIS dependencies out of the module-import path for tests
    # that mock the stage entirely.
    from affine import Affine  # noqa: PLC0415
    from rasterio.features import rasterize  # noqa: PLC0415
    from shapely.geometry import LineString, MultiPolygon, Polygon  # noqa: PLC0415

    rows, cols = target_shape
    shapes_to_burn: list[tuple[object, int]] = []

    # 1) `natural=water` polygons. Walk in input order — adapter pre-sorts by stable key.
    for polygon in polygons:
        shapes_to_burn.append((_polygon_to_shapely(polygon, Polygon), 1))

    # 2) Coastline-derived sea polygon (already a MultiPolygon in working CRS).
    if isinstance(sea_polygon, MultiPolygon) and not sea_polygon.is_empty:
        for poly in sea_polygon.geoms:
            shapes_to_burn.append((poly, 1))

    # 3) `waterway=*` lines buffered to class-specific half-widths.
    for waterway in waterways:
        width_metres = waterway_widths_metres.get(waterway.waterway_class)
        if width_metres is None or width_metres <= 0.0:
            continue
        line = LineString(waterway.geometry)
        # buffer takes a radius; the requested feature width is the diameter, so divide.
        buffered = line.buffer(width_metres / 2.0)
        if buffered.is_empty:
            continue
        shapes_to_burn.append((buffered, 1))

    if not shapes_to_burn:
        return np.zeros((rows, cols), dtype=np.bool_)

    burned = rasterize(
        shapes=shapes_to_burn,
        out_shape=(rows, cols),
        transform=Affine(*target_transform),
        fill=0,
        all_touched=True,
        dtype="uint8",
    )
    return burned.astype(np.bool_, copy=False)


def _polygon_to_shapely(polygon: WaterPolygon, polygon_cls: type) -> object:
    """Convert a domain `WaterPolygon` into a shapely `Polygon` with optional holes."""
    return polygon_cls(polygon.exterior, holes=list(polygon.holes) or None)


def _default_coastline_reconstructor(
    coastlines: Iterable[CoastlineSegment],
    bounds: GeoBounds,
) -> object:
    """Lazy adapter calling into the infrastructure coastline module.

    Defined here (not as a top-level alias) so the heavy shapely import path is exercised only
    when the stage actually runs — keeps test imports lightweight, and the import lives in a
    function body rather than at module scope where it would constitute a layering violation.
    """
    from cs_mapgen.infrastructure.coastline import reconstruct_sea_polygons  # noqa: PLC0415

    return reconstruct_sea_polygons(coastlines, bounds)


__all__ = [
    "CoastlineReconstructor",
    "CoastlineSegment",  # convenience re-export for downstream imports
    "PrepareWaterResult",
    "PrepareWaterStage",
    "WaterFeatures",
]
