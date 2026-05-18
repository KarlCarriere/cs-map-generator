"""GeoJSON encoder for `RoadNetwork`.

RFC 7946: coordinates MUST be WGS84 (longitude, latitude) in that order. Callers are responsible
for handing in a network already in EPSG:4326 — this module refuses anything else rather than
silently producing wrong-CRS GeoJSON.

Determinism: edges are serialized in the order received (callers sort upstream in
`PrepareRoadsStage`), `json.dumps` uses `sort_keys=True`, and `float.__repr__` is stable across
CPython versions, so identical input bytes in produce identical bytes out.
"""

from __future__ import annotations

import json

from cs_mapgen.domain.geometry import GeoBounds
from cs_mapgen.domain.network import RoadEdge, RoadNetwork

WGS84_EPSG = 4326
GEOJSON_MIME = "application/geo+json"


class GeoJSONEncodingError(ValueError):
    """Raised when a network cannot be encoded as GeoJSON (e.g. wrong CRS)."""


def encode_road_network_geojson(network: RoadNetwork, bounds: GeoBounds) -> bytes:
    if network.crs.epsg != WGS84_EPSG:
        raise GeoJSONEncodingError(
            f"GeoJSON requires WGS84 (EPSG:{WGS84_EPSG}) coordinates, got EPSG:{network.crs.epsg}"
        )
    if bounds.crs.epsg != WGS84_EPSG:
        raise GeoJSONEncodingError(
            f"GeoJSON bbox requires WGS84 bounds, got EPSG:{bounds.crs.epsg}"
        )

    payload = {
        "type": "FeatureCollection",
        "bbox": [bounds.west, bounds.south, bounds.east, bounds.north],
        "features": [_feature_from_edge(edge) for edge in network.edges],
    }
    return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")


def _feature_from_edge(edge: RoadEdge) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[x, y] for x, y in edge.geometry],
        },
        "properties": {
            "source": edge.source,
            "target": edge.target,
            "highway_class": edge.highway_class,
            "length_metres": edge.length_metres,
        },
    }
