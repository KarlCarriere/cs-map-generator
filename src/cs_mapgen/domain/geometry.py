"""Geographic bounds and projection value objects."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite

WGS84_EPSG = 4326
WEB_MERCATOR_EPSG = 3857
UTM_NORTH_BASE_EPSG = 32600
UTM_SOUTH_BASE_EPSG = 32700
UTM_ZONE_DEGREES = 6
UTM_FIRST_MERIDIAN_DEGREES = -180


class InvalidBoundsError(ValueError):
    """Raised when a bounding box fails geometric or geographic validation."""


@dataclass(frozen=True, slots=True)
class Projection:
    """An immutable wrapper around an EPSG code.

    Kept deliberately thin: the domain layer must not depend on pyproj. Conversion to a real
    `pyproj.CRS` happens at the infrastructure boundary.
    """

    epsg: int
    description: str = ""

    def __post_init__(self) -> None:
        if self.epsg <= 0:
            raise ValueError(f"EPSG code must be positive, got {self.epsg}")

    @classmethod
    def wgs84(cls) -> Projection:
        return cls(epsg=WGS84_EPSG, description="WGS84 lon/lat")

    @classmethod
    def web_mercator(cls) -> Projection:
        return cls(epsg=WEB_MERCATOR_EPSG, description="Web Mercator")


@dataclass(frozen=True, slots=True)
class GeoBounds:
    """An immutable axis-aligned bounding box in a known CRS.

    For WGS84, `west`/`east` are longitude in degrees, `south`/`north` are latitude in degrees.
    For metric CRSs (UTM), all four are easting/northing in metres. The semantics depend on
    `crs.epsg`; this class deliberately does not interpret them.
    """

    west: float
    south: float
    east: float
    north: float
    crs: Projection

    def __post_init__(self) -> None:
        for name, value in (
            ("west", self.west),
            ("south", self.south),
            ("east", self.east),
            ("north", self.north),
        ):
            if not isfinite(value):
                raise InvalidBoundsError(f"{name!r} must be finite, got {value!r}")
        if self.east <= self.west:
            raise InvalidBoundsError(
                f"east ({self.east}) must be strictly greater than west ({self.west}). "
                "Antimeridian-crossing bboxes are not supported in v0.1."
            )
        if self.north <= self.south:
            raise InvalidBoundsError(
                f"north ({self.north}) must be strictly greater than south ({self.south})"
            )
        if self.crs.epsg == WGS84_EPSG:
            if not (-180.0 <= self.west < self.east <= 180.0):
                raise InvalidBoundsError("WGS84 longitudes must lie within [-180, 180]")
            if not (-90.0 <= self.south < self.north <= 90.0):
                raise InvalidBoundsError("WGS84 latitudes must lie within [-90, 90]")

    @property
    def width(self) -> float:
        return self.east - self.west

    @property
    def height(self) -> float:
        return self.north - self.south

    @property
    def centroid(self) -> tuple[float, float]:
        return ((self.west + self.east) / 2.0, (self.south + self.north) / 2.0)

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Return `(west, south, east, north)`. This is the OSMnx 2.x convention."""
        return (self.west, self.south, self.east, self.north)


def pick_utm_projection(bounds: GeoBounds) -> Projection:
    """Pick a UTM zone for the bbox centroid. WGS84 input only.

    Uses EPSG 326xx for the northern hemisphere, 327xx for the southern. This is the canonical
    choice for typical city-sized bboxes; for polar regions or bboxes spanning many zones, an
    equal-area projection should be used instead (deferred to a later phase).
    """
    if bounds.crs.epsg != WGS84_EPSG:
        raise InvalidBoundsError(
            f"UTM zone selection requires WGS84 input, got EPSG:{bounds.crs.epsg}"
        )
    centroid_lon, centroid_lat = bounds.centroid
    zone_number = int(floor((centroid_lon - UTM_FIRST_MERIDIAN_DEGREES) / UTM_ZONE_DEGREES)) + 1
    # Polar caps — UTM is undefined above 84N / below 80S. Refuse rather than silently produce
    # a wrong projection.
    if centroid_lat > 84.0 or centroid_lat < -80.0:
        raise InvalidBoundsError(
            "UTM is undefined for the polar regions; UPS projection support is deferred."
        )
    base = UTM_NORTH_BASE_EPSG if centroid_lat >= 0 else UTM_SOUTH_BASE_EPSG
    return Projection(
        epsg=base + zone_number,
        description=f"UTM zone {zone_number}{'N' if centroid_lat >= 0 else 'S'}",
    )
