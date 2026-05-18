"""User-intent map extent value objects.

The user can express the map they want in two equivalent ways:

- A center coordinate plus a tile-radius (natural for Cities: Skylines, since the playable area
  is a square grid of tiles centred on a starting tile).
- An explicit WGS84 bounding box (power-user / scripting path).

Both shapes are captured here as frozen value objects. A separate pure resolver in the
application layer (`cs_mapgen.application.extent_resolver.resolve_extent`) translates either
shape into a `GeoBounds` that the rest of the pipeline already accepts.

This module has zero framework dependencies — it is part of the domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Literal

from cs_mapgen.domain.geometry import GeoBounds

MIN_LATITUDE_DEGREES = -90.0
MAX_LATITUDE_DEGREES = 90.0
MIN_LONGITUDE_DEGREES = -180.0
MAX_LONGITUDE_DEGREES = 180.0

CENTER_KIND = "center"
BOUNDS_KIND = "bounds"


class InvalidExtentError(ValueError):
    """Raised when a `MapExtent` fails validation at construction or resolution time."""


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """A WGS84 lon/lat point.

    Stored as `(longitude, latitude)` floats. Order matches the xy-first convention used
    throughout the project (`always_xy=True`). Construction validates finiteness and bounds.
    """

    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if not isfinite(self.longitude):
            raise InvalidExtentError(f"longitude must be finite, got {self.longitude!r}")
        if not isfinite(self.latitude):
            raise InvalidExtentError(f"latitude must be finite, got {self.latitude!r}")
        if not MIN_LONGITUDE_DEGREES <= self.longitude <= MAX_LONGITUDE_DEGREES:
            raise InvalidExtentError(
                f"longitude {self.longitude} out of WGS84 range "
                f"[{MIN_LONGITUDE_DEGREES}, {MAX_LONGITUDE_DEGREES}]"
            )
        if not MIN_LATITUDE_DEGREES <= self.latitude <= MAX_LATITUDE_DEGREES:
            raise InvalidExtentError(
                f"latitude {self.latitude} out of WGS84 range "
                f"[{MIN_LATITUDE_DEGREES}, {MAX_LATITUDE_DEGREES}]"
            )


@dataclass(frozen=True, slots=True)
class CenterExtent:
    """Map intent expressed as `(center, radius_tiles, target_id)`.

    `radius_tiles` is the number of in-game tiles in each cardinal direction beyond the centre
    tile, so the total side length is `(2 * radius_tiles + 1) * tile_side_metres`. The
    `target_id` binds this intent to a concrete per-tile metric in `target_specs.py`.

    The `kind` discriminator is a constant tag set at construction time so the tagged-union
    consumer can dispatch on `extent.kind` without isinstance. It is `init=False` so callers
    never have to (and never accidentally can) supply a wrong value.
    """

    center: GeoPoint
    radius_tiles: int
    target_id: str
    kind: Literal["center"] = field(default=CENTER_KIND, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.radius_tiles, int) or isinstance(self.radius_tiles, bool):
            # `bool` is a subclass of `int`; reject it explicitly so a stray `True` cannot
            # silently behave as `radius_tiles=1`.
            raise InvalidExtentError(
                f"radius_tiles must be an int, got {type(self.radius_tiles).__name__}"
            )
        if self.radius_tiles < 0:
            raise InvalidExtentError(
                f"radius_tiles must be non-negative, got {self.radius_tiles}"
            )
        if not self.target_id:
            raise InvalidExtentError("CenterExtent.target_id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class BoundsExtent:
    """Map intent expressed as an explicit WGS84 `GeoBounds`."""

    bounds: GeoBounds
    kind: Literal["bounds"] = field(default=BOUNDS_KIND, init=False)


# Tagged union. Consumers discriminate on the `kind` literal or via `isinstance`.
MapExtent = CenterExtent | BoundsExtent
