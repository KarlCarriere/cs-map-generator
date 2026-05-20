"""Tests for `OSMnxWaterSource` cache-hit + cache-roundtrip paths. No network."""

from __future__ import annotations

from pathlib import Path

import pytest

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.water import (
    CoastlineSegment,
    WaterFeatures,
    WaterPolygon,
    Waterway,
)
from cs_mapgen.infrastructure.osm.osmnx_water_source import OSMnxWaterSource

WGS84 = Projection.wgs84()

# Allowlisted waterway classes from the source module. Tests use one of them.
RIVER_CLASS = "river"


def _bounds() -> GeoBounds:
    return GeoBounds(west=0.0, south=0.0, east=1.0, north=1.0, crs=WGS84)


def _hand_built_features() -> WaterFeatures:
    polygon = WaterPolygon(
        exterior=(
            (0.2, 0.2),
            (0.4, 0.2),
            (0.4, 0.4),
            (0.2, 0.4),
            (0.2, 0.2),
        ),
    )
    waterway = Waterway(
        geometry=((0.1, 0.5), (0.5, 0.5), (0.9, 0.5)),
        waterway_class=RIVER_CLASS,
    )
    coastline = CoastlineSegment(
        geometry=((-0.5, 0.8), (0.5, 0.8), (1.5, 0.8)),
    )
    return WaterFeatures(
        polygons=(polygon,),
        waterways=(waterway,),
        coastlines=(coastline,),
        crs=WGS84,
    )


def test_should_roundtrip_features_through_cache(
    tmp_path: Path,
    stage_context: StageContext,
) -> None:
    """First fetch writes cache; second fetch reads cache; bytes equal up to feature equality."""
    fixtures = _hand_built_features()

    # First-pass loader injects the hand-built features (no network).
    def loader_round_one(bounds: GeoBounds, tags: dict[str, object]):  # noqa: ARG001
        from shapely.geometry import LineString, Polygon  # noqa: PLC0415

        if "natural" in tags and "water" in (tags["natural"] or []):
            import geopandas as gpd  # noqa: PLC0415

            poly = Polygon(fixtures.polygons[0].exterior)
            return gpd.GeoDataFrame({"geometry": [poly]}, geometry="geometry", crs="EPSG:4326")
        if "waterway" in tags:
            import geopandas as gpd  # noqa: PLC0415

            line = LineString(fixtures.waterways[0].geometry)
            return gpd.GeoDataFrame(
                {"geometry": [line], "waterway": [RIVER_CLASS]},
                geometry="geometry",
                crs="EPSG:4326",
            )
        if "natural" in tags and "coastline" in (tags["natural"] or []):
            import geopandas as gpd  # noqa: PLC0415

            line = LineString(fixtures.coastlines[0].geometry)
            return gpd.GeoDataFrame({"geometry": [line]}, geometry="geometry", crs="EPSG:4326")
        # Empty GeoDataFrame for any other query.
        import geopandas as gpd  # noqa: PLC0415

        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    source = OSMnxWaterSource(cache_directory=cache_dir, features_loader=loader_round_one)
    bounds = _bounds()
    first = source.fetch_water(bounds, stage_context)

    assert len(first.polygons) == 1
    assert len(first.waterways) == 1
    assert len(first.coastlines) == 1

    # Second-pass: loader must NOT be called — it would raise if invoked. Verifies cache hit.
    def loader_round_two(bounds: GeoBounds, tags: dict[str, object]):  # noqa: ARG001
        raise AssertionError("Cache miss should not have happened; loader was called")

    source_two = OSMnxWaterSource(cache_directory=cache_dir, features_loader=loader_round_two)
    second = source_two.fetch_water(bounds, stage_context)

    # Polygons, waterways, coastlines all match the first-pass output structurally.
    assert second.polygons[0].exterior == first.polygons[0].exterior
    assert second.waterways[0].waterway_class == first.waterways[0].waterway_class
    assert second.waterways[0].geometry == first.waterways[0].geometry
    assert second.coastlines[0].geometry == first.coastlines[0].geometry


def test_should_skip_unknown_waterway_classes(
    tmp_path: Path,
    stage_context: StageContext,
) -> None:
    def loader(bounds: GeoBounds, tags: dict[str, object]):  # noqa: ARG001
        from shapely.geometry import LineString  # noqa: PLC0415
        import geopandas as gpd  # noqa: PLC0415

        if "waterway" in tags:
            # Mix one river (allowed) with one drain (skipped).
            return gpd.GeoDataFrame(
                {
                    "geometry": [
                        LineString([(0.1, 0.5), (0.9, 0.5)]),
                        LineString([(0.1, 0.6), (0.9, 0.6)]),
                    ],
                    "waterway": [RIVER_CLASS, "drain"],
                },
                geometry="geometry",
                crs="EPSG:4326",
            )
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    source = OSMnxWaterSource(cache_directory=cache_dir, features_loader=loader)

    result = source.fetch_water(_bounds(), stage_context)

    assert len(result.waterways) == 1
    assert result.waterways[0].waterway_class == RIVER_CLASS


def test_should_ignore_corrupt_cache_and_refetch(
    tmp_path: Path,
    stage_context: StageContext,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    source = OSMnxWaterSource(cache_directory=cache_dir, features_loader=_empty_loader)

    # Pre-populate the would-be cache file with garbage bytes.
    cache_path = source._cache_path(_bounds())  # noqa: SLF001 — testing the private resolver
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"not a valid water cache")

    # Should NOT raise — corrupt cache is silently re-fetched.
    result = source.fetch_water(_bounds(), stage_context)

    assert result.is_empty


def _empty_loader(bounds: GeoBounds, tags: dict[str, object]):  # noqa: ARG001
    import geopandas as gpd  # noqa: PLC0415

    return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")


def test_should_treat_insufficient_response_as_empty_layer(
    tmp_path: Path,
    stage_context: StageContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inland bbox queries (e.g. `natural=coastline`) return zero features.

    OSMnx 2.x signals this with `InsufficientResponseError`. The source must treat it as an
    empty layer rather than letting the pipeline crash.
    """
    import osmnx  # noqa: PLC0415
    from osmnx._errors import InsufficientResponseError  # noqa: PLC0415

    def raise_insufficient(*_args: object, **_kwargs: object) -> object:
        raise InsufficientResponseError("No matching features.")

    monkeypatch.setattr(osmnx.features, "features_from_bbox", raise_insufficient)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    # No `features_loader`: forces the OSMnx-real branch where the catch lives.
    source = OSMnxWaterSource(cache_directory=cache_dir)

    result = source.fetch_water(_bounds(), stage_context)

    assert result.is_empty


pytestmark = pytest.mark.requires_gis
