"""Unit tests for the road-network GeoJSON encoder."""

from __future__ import annotations

import json

import pytest

from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.network import RoadEdge, RoadNetwork, RoadNode
from cs_mapgen.infrastructure.export._geojson import (
    GeoJSONEncodingError,
    encode_road_network_geojson,
)

WGS84 = Projection.wgs84()
UTM_19N_EPSG = 32619


def _wgs84_bounds() -> GeoBounds:
    return GeoBounds(west=-71.3, south=46.7, east=-71.1, north=46.9, crs=WGS84)


def _single_edge_network() -> RoadNetwork:
    return RoadNetwork(
        nodes=(
            RoadNode(node_id=1, x=-71.30, y=46.70),
            RoadNode(node_id=2, x=-71.10, y=46.90),
        ),
        edges=(
            RoadEdge(
                source=1,
                target=2,
                geometry=((-71.30, 46.70), (-71.20, 46.80), (-71.10, 46.90)),
                highway_class="primary",
                length_metres=1234.5,
            ),
        ),
        crs=WGS84,
    )


def test_should_encode_road_network_as_feature_collection_when_input_is_wgs84() -> None:
    network = _single_edge_network()

    raw = encode_road_network_geojson(network, _wgs84_bounds())
    payload = json.loads(raw)

    assert payload["type"] == "FeatureCollection"
    assert payload["bbox"] == [-71.3, 46.7, -71.1, 46.9]
    assert len(payload["features"]) == 1
    feature = payload["features"][0]
    assert feature["geometry"]["type"] == "LineString"
    assert feature["geometry"]["coordinates"] == [[-71.30, 46.70], [-71.20, 46.80], [-71.10, 46.90]]
    assert feature["properties"] == {
        "source": 1,
        "target": 2,
        "highway_class": "primary",
        "length_metres": 1234.5,
    }


def test_should_emit_empty_feature_collection_when_network_has_no_edges() -> None:
    empty_network = RoadNetwork(nodes=(), edges=(), crs=WGS84)

    payload = json.loads(encode_road_network_geojson(empty_network, _wgs84_bounds()))

    assert payload["features"] == []
    assert payload["bbox"] == [-71.3, 46.7, -71.1, 46.9]


def test_should_produce_byte_identical_output_when_encoding_same_input_twice() -> None:
    network = _single_edge_network()
    bounds = _wgs84_bounds()

    first = encode_road_network_geojson(network, bounds)
    second = encode_road_network_geojson(network, bounds)

    assert first == second


def test_should_reject_network_when_crs_is_not_wgs84() -> None:
    utm_network = RoadNetwork(
        nodes=(RoadNode(node_id=1, x=0.0, y=0.0), RoadNode(node_id=2, x=10.0, y=10.0)),
        edges=(
            RoadEdge(
                source=1,
                target=2,
                geometry=((0.0, 0.0), (10.0, 10.0)),
                highway_class="primary",
                length_metres=14.14,
            ),
        ),
        crs=Projection(epsg=UTM_19N_EPSG, description="UTM 19N"),
    )

    with pytest.raises(GeoJSONEncodingError, match="WGS84"):
        encode_road_network_geojson(utm_network, _wgs84_bounds())


def test_should_reject_bounds_when_crs_is_not_wgs84() -> None:
    network = _single_edge_network()
    utm_bounds = GeoBounds(
        west=0.0,
        south=0.0,
        east=10.0,
        north=10.0,
        crs=Projection(epsg=UTM_19N_EPSG, description="UTM 19N"),
    )

    with pytest.raises(GeoJSONEncodingError, match="bbox"):
        encode_road_network_geojson(network, utm_bounds)
