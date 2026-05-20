"""SRTM 1-arc-second tile naming math.

SRTM 1-arc-second (SRTMGL1) tiles are named `N00E000.hgt` / `S01W001.hgt` etc., each covering a
1° × 1° square indexed by the SW corner. A bbox is covered by the integer floor of its corners,
inclusive on both sides.
"""

from __future__ import annotations

from math import ceil, floor

from cs_mapgen.domain.geometry import GeoBounds, Projection

WGS84_EPSG = 4326


def srtm_tile_name(lat_floor: int, lon_floor: int) -> str:
    """Return the canonical SRTM hgt tile name for the given SW corner."""
    lat_prefix = "N" if lat_floor >= 0 else "S"
    lon_prefix = "E" if lon_floor >= 0 else "W"
    return f"{lat_prefix}{abs(lat_floor):02d}{lon_prefix}{abs(lon_floor):03d}.hgt"


def tiles_covering(bounds: GeoBounds) -> tuple[str, ...]:
    """Enumerate SRTM tile names covering the bbox, sorted for determinism.

    Bounds must be in WGS84 (EPSG:4326). One tile of padding on each side is included to mask
    seam artifacts during reprojection.
    """
    if bounds.crs != Projection.wgs84() and bounds.crs.epsg != WGS84_EPSG:
        raise ValueError(f"SRTM tile indexing requires WGS84 bounds, got EPSG:{bounds.crs.epsg}")
    lat_start = floor(bounds.south) - 1
    lat_stop = ceil(bounds.north) + 1
    lon_start = floor(bounds.west) - 1
    lon_stop = ceil(bounds.east) + 1
    # Sorted by latitude then longitude for deterministic ordering.
    names = [
        srtm_tile_name(lat, lon)
        for lat in range(lat_start, lat_stop)
        for lon in range(lon_start, lon_stop)
    ]
    return tuple(sorted(names))
