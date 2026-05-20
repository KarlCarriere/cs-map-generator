"""OSMnx-backed water source.

Pulls three OSM categories and returns them as a domain `WaterFeatures`:

- `natural=water` (lakes, reservoirs, wide rivers represented as polygons).
- `waterway=*` (linear features: river, stream, canal). Filtered downstream by class allowlist.
- `natural=coastline` (open polylines; reconstructed against bbox in `infrastructure/coastline/`).

OSMnx 2.x API (verified against the upstream docs at the time of writing):

    osmnx.features.features_from_bbox(bbox=(west, south, east, north), tags={...})
    # returns a geopandas.GeoDataFrame multi-indexed by (element_type, osmid).

The signature changed across the 1.x → 2.x boundary (positional args → keyword `bbox=` tuple
with `(west, south, east, north)` ordering). We pin `osmnx~=2.1` in `pyproject.toml`.

Determinism: cache key is `(bbox, osmnx_version, tag_query_hash)`. Cached responses are a
Parquet dump of the WaterFeatures coordinates (not the raw GeoDataFrame) so the on-disk
representation is also typed and lockfile-stable. Iteration over the GeoDataFrame is sorted by
its multi-index BEFORE conversion to `WaterFeatures`, so output is deterministic across runs
even if upstream OSMnx changes its dict iteration order.

This adapter prefers cache-first; cache misses go through OSMnx (which talks to Overpass). In
tests, inject a `features_loader` callable to bypass OSMnx entirely.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.water import (
    CoastlineSegment,
    WaterFeatures,
    WaterPolygon,
    Waterway,
)

if TYPE_CHECKING:
    import geopandas as gpd

WATER_POLYGON_TAGS: dict[str, object] = {"natural": ["water"]}
WATERWAY_TAGS: dict[str, object] = {"waterway": ["river", "stream", "canal"]}
COASTLINE_TAGS: dict[str, object] = {"natural": ["coastline"]}

CACHE_SUBDIRECTORY = "osm_water"
CACHE_FILE_VERSION = 1
PROVIDER_VERSION = "osmnx~=2.1"

# Allowlist of waterway classes — must match the keys in `WATERWAY_WIDTH_METRES`. Out-of-list
# classes (e.g. drain, ditch) are dropped at fetch time so the cache never has to store them.
ALLOWED_WATERWAY_CLASSES = frozenset({"river", "stream", "canal"})


FeaturesLoader = Callable[[GeoBounds, dict[str, object]], "gpd.GeoDataFrame"]


class OSMnxWaterSource:
    """Fetch + cache OSM water features via OSMnx 2.x features API."""

    def __init__(
        self,
        cache_directory: Path,
        features_loader: FeaturesLoader | None = None,
    ) -> None:
        self._cache_directory = cache_directory
        self._features_loader = features_loader

    def fetch_water(self, bounds: GeoBounds, context: StageContext) -> WaterFeatures:
        cache_path = self._cache_path(bounds)
        cached = _load_cached_features(cache_path, bounds.crs)
        if cached is not None:
            context.logger.info(
                "water.cache_hit", extra={"path": str(cache_path), "bbox": bounds.as_tuple()}
            )
            return cached

        context.logger.info(
            "water.cache_miss",
            extra={"path": str(cache_path), "bbox": bounds.as_tuple()},
        )
        polygons_gdf = self._load_geodataframe(bounds, WATER_POLYGON_TAGS)
        waterways_gdf = self._load_geodataframe(bounds, WATERWAY_TAGS)
        coastlines_gdf = self._load_geodataframe(bounds, COASTLINE_TAGS)

        polygons = _extract_water_polygons(polygons_gdf)
        waterways = _extract_waterways(waterways_gdf)
        coastlines = _extract_coastlines(coastlines_gdf)

        features = WaterFeatures(
            polygons=polygons,
            waterways=waterways,
            coastlines=coastlines,
            crs=bounds.crs,
        )
        _store_cached_features(cache_path, features)
        return features

    def _cache_path(self, bounds: GeoBounds) -> Path:
        key_source = json.dumps(
            {
                "bbox": bounds.as_tuple(),
                "crs_epsg": bounds.crs.epsg,
                "provider_version": PROVIDER_VERSION,
                "file_version": CACHE_FILE_VERSION,
                "polygon_tags": WATER_POLYGON_TAGS,
                "waterway_tags": WATERWAY_TAGS,
                "coastline_tags": COASTLINE_TAGS,
            },
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(key_source).hexdigest()[:32]
        return self._cache_directory / CACHE_SUBDIRECTORY / f"{digest}.bin"

    def _load_geodataframe(
        self,
        bounds: GeoBounds,
        tags: dict[str, object],
    ) -> "gpd.GeoDataFrame":
        if self._features_loader is not None:
            return self._features_loader(bounds, tags)
        # Local import — OSMnx is heavy and tests usually inject `features_loader`.
        import geopandas as gpd  # noqa: PLC0415
        import osmnx  # noqa: PLC0415
        from osmnx._errors import InsufficientResponseError  # noqa: PLC0415

        # OSMnx 2.x: `features_from_bbox(bbox=(west, south, east, north), tags=...)`. We pin
        # the version range in pyproject.toml so this signature is stable.
        #
        # OSMnx raises `InsufficientResponseError` (a `ValueError` subclass) when no features
        # match — this is the expected outcome for inland tiles querying `natural=coastline`,
        # or arid tiles querying `natural=water`. Treat it as an empty result rather than a
        # pipeline failure.
        try:
            return osmnx.features.features_from_bbox(bbox=bounds.as_tuple(), tags=tags)
        except InsufficientResponseError:
            return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")


def _extract_water_polygons(
    gdf: "gpd.GeoDataFrame | None",
) -> tuple[WaterPolygon, ...]:
    if gdf is None or gdf.empty:
        return ()
    sorted_gdf = _sort_by_index(gdf)
    polygons: list[WaterPolygon] = []
    for geom in sorted_gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        polygons.extend(_split_to_polygons(geom))
    return tuple(polygons)


def _extract_waterways(
    gdf: "gpd.GeoDataFrame | None",
) -> tuple[Waterway, ...]:
    if gdf is None or gdf.empty:
        return ()
    if "waterway" not in gdf.columns:
        return ()
    sorted_gdf = _sort_by_index(gdf)
    waterways: list[Waterway] = []
    for _, row in sorted_gdf.iterrows():
        waterway_class = _normalise_tag_value(row.get("waterway", ""))
        if waterway_class not in ALLOWED_WATERWAY_CLASSES:
            continue
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        for line in _split_to_linestrings(geom):
            waterways.append(
                Waterway(
                    geometry=tuple((float(x), float(y)) for x, y in line.coords),
                    waterway_class=waterway_class,
                )
            )
    return tuple(waterways)


def _normalise_tag_value(value: object) -> str:
    """Coerce an OSM tag value into a single string.

    OSMnx occasionally surfaces multi-valued tags as a Python list (`["river", "stream"]`),
    and pandas sometimes wraps NaN where the column has mixed types. We pick the first
    string-representable value; empty / NaN → empty string (filtered out downstream).
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    text = str(value)
    if text == "nan":
        return ""
    return text


def _extract_coastlines(
    gdf: "gpd.GeoDataFrame | None",
) -> tuple[CoastlineSegment, ...]:
    if gdf is None or gdf.empty:
        return ()
    sorted_gdf = _sort_by_index(gdf)
    segments: list[CoastlineSegment] = []
    for geom in sorted_gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        for line in _split_to_linestrings(geom):
            segments.append(
                CoastlineSegment(
                    geometry=tuple((float(x), float(y)) for x, y in line.coords),
                )
            )
    return tuple(segments)


def _sort_by_index(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    # OSMnx returns a MultiIndex of (element_type, osmid). Sorting by both keys gives stable
    # iteration across runs regardless of what order the upstream Overpass response came in.
    return gdf.sort_index()


def _split_to_polygons(geom: object) -> list[WaterPolygon]:
    from shapely.geometry import MultiPolygon, Polygon  # noqa: PLC0415

    if isinstance(geom, Polygon):
        return [_polygon_to_domain(geom)]
    if isinstance(geom, MultiPolygon):
        return [_polygon_to_domain(part) for part in geom.geoms]
    return []


def _split_to_linestrings(geom: object) -> list[object]:
    from shapely.geometry import LineString, MultiLineString  # noqa: PLC0415

    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return []


def _polygon_to_domain(polygon: object) -> WaterPolygon:
    exterior = tuple((float(x), float(y)) for x, y in polygon.exterior.coords)  # type: ignore[attr-defined]
    holes = tuple(
        tuple((float(x), float(y)) for x, y in interior.coords)
        for interior in polygon.interiors  # type: ignore[attr-defined]
    )
    return WaterPolygon(exterior=exterior, holes=holes)


# --- Cache serialisation ----------------------------------------------------------------------
#
# We store WaterFeatures as a compact binary blob rather than a Parquet dump, for three reasons:
# 1. It avoids pulling in pyarrow at the OSM source level; the cache layer should not balloon
#    the dependency footprint.
# 2. The format is content-addressed by `_cache_path` — schema drift is impossible without a
#    new digest.
# 3. The blob is deterministic given a fixed `WaterFeatures` instance (sorted coordinates and
#    classes, fixed integer encoding, zlib at default level for stable bytes).

_MAGIC = b"WFv1"
_COORD_STRUCT = struct.Struct("<dd")


def _store_cached_features(path: Path, features: WaterFeatures) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = bytearray()
    payload += _MAGIC
    payload += struct.pack("<I", features.crs.epsg)
    payload += _encode_polygons(features.polygons)
    payload += _encode_waterways(features.waterways)
    payload += _encode_coastlines(features.coastlines)
    path.write_bytes(zlib.compress(bytes(payload), level=6))


def _load_cached_features(path: Path, crs: Projection) -> WaterFeatures | None:
    if not path.exists():
        return None
    try:
        raw = zlib.decompress(path.read_bytes())
    except zlib.error:
        # Corrupt cache — pretend it never existed; the caller will re-fetch and overwrite.
        return None
    if not raw.startswith(_MAGIC):
        return None
    cursor = len(_MAGIC)
    (epsg,) = struct.unpack_from("<I", raw, cursor)
    cursor += 4
    if epsg != crs.epsg:
        return None
    polygons, cursor = _decode_polygons(raw, cursor)
    waterways, cursor = _decode_waterways(raw, cursor)
    coastlines, _ = _decode_coastlines(raw, cursor)
    return WaterFeatures(
        polygons=polygons,
        waterways=waterways,
        coastlines=coastlines,
        crs=crs,
    )


def _encode_polygons(polygons: tuple[WaterPolygon, ...]) -> bytes:
    buffer = bytearray()
    buffer += struct.pack("<I", len(polygons))
    for polygon in polygons:
        buffer += _encode_ring(polygon.exterior)
        buffer += struct.pack("<I", len(polygon.holes))
        for hole in polygon.holes:
            buffer += _encode_ring(hole)
    return bytes(buffer)


def _decode_polygons(raw: bytes, cursor: int) -> tuple[tuple[WaterPolygon, ...], int]:
    (count,) = struct.unpack_from("<I", raw, cursor)
    cursor += 4
    polygons: list[WaterPolygon] = []
    for _ in range(count):
        exterior, cursor = _decode_ring(raw, cursor)
        (hole_count,) = struct.unpack_from("<I", raw, cursor)
        cursor += 4
        holes: list[tuple[tuple[float, float], ...]] = []
        for _hole_index in range(hole_count):
            hole, cursor = _decode_ring(raw, cursor)
            holes.append(hole)
        polygons.append(WaterPolygon(exterior=exterior, holes=tuple(holes)))
    return tuple(polygons), cursor


def _encode_waterways(waterways: tuple[Waterway, ...]) -> bytes:
    buffer = bytearray()
    buffer += struct.pack("<I", len(waterways))
    for waterway in waterways:
        class_bytes = waterway.waterway_class.encode("utf-8")
        buffer += struct.pack("<I", len(class_bytes))
        buffer += class_bytes
        buffer += _encode_ring(waterway.geometry)
    return bytes(buffer)


def _decode_waterways(raw: bytes, cursor: int) -> tuple[tuple[Waterway, ...], int]:
    (count,) = struct.unpack_from("<I", raw, cursor)
    cursor += 4
    waterways: list[Waterway] = []
    for _ in range(count):
        (name_length,) = struct.unpack_from("<I", raw, cursor)
        cursor += 4
        name = raw[cursor : cursor + name_length].decode("utf-8")
        cursor += name_length
        geometry, cursor = _decode_ring(raw, cursor)
        waterways.append(Waterway(geometry=geometry, waterway_class=name))
    return tuple(waterways), cursor


def _encode_coastlines(coastlines: tuple[CoastlineSegment, ...]) -> bytes:
    buffer = bytearray()
    buffer += struct.pack("<I", len(coastlines))
    for segment in coastlines:
        buffer += _encode_ring(segment.geometry)
    return bytes(buffer)


def _decode_coastlines(raw: bytes, cursor: int) -> tuple[tuple[CoastlineSegment, ...], int]:
    (count,) = struct.unpack_from("<I", raw, cursor)
    cursor += 4
    segments: list[CoastlineSegment] = []
    for _ in range(count):
        geometry, cursor = _decode_ring(raw, cursor)
        segments.append(CoastlineSegment(geometry=geometry))
    return tuple(segments), cursor


def _encode_ring(ring: tuple[tuple[float, float], ...]) -> bytes:
    buffer = bytearray()
    buffer += struct.pack("<I", len(ring))
    for x, y in ring:
        buffer += _COORD_STRUCT.pack(x, y)
    return bytes(buffer)


def _decode_ring(raw: bytes, cursor: int) -> tuple[tuple[tuple[float, float], ...], int]:
    (count,) = struct.unpack_from("<I", raw, cursor)
    cursor += 4
    coords: list[tuple[float, float]] = []
    for _ in range(count):
        x, y = _COORD_STRUCT.unpack_from(raw, cursor)
        cursor += _COORD_STRUCT.size
        coords.append((x, y))
    return tuple(coords), cursor
