"""Water value objects: masks aligned to the heightmap grid and raw water features.

These are pure domain types with zero framework dependencies. Numpy arrays are conventionally
treated as immutable downstream — stages either return a new array or copy on write.

The water mask is a binary raster (`True` where water covers the cell, `False` otherwise) aligned
to the same grid as the `Heightmap` it accompanies. Alignment is enforced at the `MapTile`
boundary by `prepare_water` — this module only validates intra-object invariants.

`WaterFeatures` carries the raw, ingested-but-not-yet-rasterised geometry. It crosses the
application/infrastructure boundary as a transient input to `PrepareWaterStage` — keeping it in
the domain layer rather than in `application/` lets infrastructure adapters return a typed value
instead of an opaque DTO, and lets stage tests construct one directly without importing
infrastructure.

Coordinates are stored as plain tuples (not shapely geometries) so the domain stays
framework-free. The infrastructure adapter is responsible for translating from
geopandas/shapely into these tuple representations at ingest time.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cs_mapgen.domain.geometry import Projection

WATER_MASK_DTYPE = np.bool_
AFFINE_TUPLE_LENGTH = 6
MIN_POLYGON_RING_VERTICES = 4  # closed linear ring: at least 3 unique + closing repeat
MIN_LINESTRING_VERTICES = 2


@dataclass(frozen=True, slots=True)
class WaterMask:
    """A binary water mask aligned to a raster grid.

    `mask[row, col]` is `True` where the cell is covered by water (sea, lake, river, canal),
    `False` otherwise. `transform` is the same 6-tuple affine convention used by `DEMTile` and
    the working CRS is carried explicitly.

    Invariants enforced at construction:
    - `mask` is a 2D boolean array.
    - `transform` is a 6-tuple of floats (a, b, c, d, e, f) in the rasterio convention.
    """

    mask: NDArray[np.bool_]
    transform: tuple[float, float, float, float, float, float]
    crs: Projection

    def __post_init__(self) -> None:
        if self.mask.ndim != 2:
            raise ValueError(f"WaterMask must be 2D, got shape {self.mask.shape}")
        if self.mask.dtype != WATER_MASK_DTYPE:
            raise ValueError(
                f"WaterMask must be bool dtype, got {self.mask.dtype}. "
                "Convert with `.astype(bool)` before construction."
            )
        if len(self.transform) != AFFINE_TUPLE_LENGTH:
            raise ValueError(
                f"Affine transform must be a 6-tuple (a, b, c, d, e, f), got {self.transform}"
            )

    @property
    def shape(self) -> tuple[int, int]:
        return self.mask.shape  # type: ignore[return-value]

    @property
    def coverage_fraction(self) -> float:
        """Fraction of cells covered by water, in [0, 1]. Useful for logging + sanity checks."""
        if self.mask.size == 0:
            return 0.0
        return float(self.mask.sum()) / float(self.mask.size)


# OSM `waterway` tag values we treat as carved water. Other values (drain, ditch, …) are
# explicitly out of scope — they are too small to register at heightmap pixel resolution. The
# defaults below are documented in ADR 0005; callers can override via `PrepareWaterStage`.
WATERWAY_WIDTH_METRES: dict[str, float] = {
    "river": 20.0,
    "stream": 5.0,
    "canal": 15.0,
}


@dataclass(frozen=True, slots=True)
class WaterPolygon:
    """A single water polygon as a tuple of exterior + holes, each a coordinate ring.

    Coordinates are `(x, y)` in `WaterFeatures.crs` (WGS84 at ingest, working CRS after the
    prepare stage). Holes are inner rings; an empty `holes` tuple is the common case for lakes.

    A linear ring is a closed polyline: the first and last coordinates are equal. Construction
    checks the ring has at least 4 vertices (3 unique + closing repeat).
    """

    exterior: tuple[tuple[float, float], ...]
    holes: tuple[tuple[tuple[float, float], ...], ...] = ()

    def __post_init__(self) -> None:
        if len(self.exterior) < MIN_POLYGON_RING_VERTICES:
            raise ValueError(
                f"WaterPolygon exterior ring must have at least {MIN_POLYGON_RING_VERTICES} "
                f"vertices (closed), got {len(self.exterior)}"
            )
        for index, hole in enumerate(self.holes):
            if len(hole) < MIN_POLYGON_RING_VERTICES:
                raise ValueError(
                    f"WaterPolygon hole {index} must have at least {MIN_POLYGON_RING_VERTICES} "
                    f"vertices (closed), got {len(hole)}"
                )


@dataclass(frozen=True, slots=True)
class Waterway:
    """A linear water feature (river, stream, canal). One-dimensional in the OSM model.

    `geometry` is a tuple of `(x, y)` vertices including endpoints, in `WaterFeatures.crs`.
    `waterway_class` is the OSM `waterway=` tag value (e.g. `river`, `stream`, `canal`). The
    `prepare_water` stage uses the class to look up a buffer width in metres before rasterising.
    """

    geometry: tuple[tuple[float, float], ...]
    waterway_class: str

    def __post_init__(self) -> None:
        if len(self.geometry) < MIN_LINESTRING_VERTICES:
            raise ValueError(
                f"Waterway geometry must have at least {MIN_LINESTRING_VERTICES} vertices, "
                f"got {len(self.geometry)}"
            )
        if not self.waterway_class:
            raise ValueError("waterway_class must be a non-empty string")


@dataclass(frozen=True, slots=True)
class CoastlineSegment:
    """An OSM `natural=coastline` open polyline.

    OSM convention: coastline is a directed line with **land on the left, sea on the right**.
    The reconstruction step in `infrastructure/coastline/` consumes these segments together with
    the bbox to close them into a sea polygon.
    """

    geometry: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.geometry) < MIN_LINESTRING_VERTICES:
            raise ValueError(
                f"CoastlineSegment must have at least {MIN_LINESTRING_VERTICES} vertices, "
                f"got {len(self.geometry)}"
            )


@dataclass(frozen=True, slots=True)
class WaterFeatures:
    """Raw water features ingested from OSM, ready for the `prepare_water` stage.

    All three collections are tuples (immutable, ordered) so iteration order is deterministic.
    Adapter implementations sort by stable keys (feature id, geometry hash) before constructing
    this object — the domain enforces structural shape, not ordering policy.
    """

    polygons: tuple[WaterPolygon, ...]
    waterways: tuple[Waterway, ...]
    coastlines: tuple[CoastlineSegment, ...]
    crs: Projection

    @property
    def is_empty(self) -> bool:
        return not (self.polygons or self.waterways or self.coastlines)
