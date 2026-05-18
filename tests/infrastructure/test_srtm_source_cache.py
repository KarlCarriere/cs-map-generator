"""Tests for `SRTMDEMSource` cache-hit path. Network is never touched."""

from __future__ import annotations

from pathlib import Path

import pytest

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.infrastructure.dem.srtm_source import SRTMDEMSource, SRTMTileNotFoundError

FIXTURE_TILE_SIDE_SAMPLES = 11


def test_should_load_dem_tile_when_cache_already_contains_tiles(
    fixture_bbox: GeoBounds,
    srtm_cache_directory: Path,
    stage_context: StageContext,
) -> None:
    source = SRTMDEMSource(
        cache_directory=srtm_cache_directory,
        base_url="http://test.invalid/",
        tile_side_samples=FIXTURE_TILE_SIDE_SAMPLES,
    )

    tile = source.fetch(fixture_bbox, stage_context)

    assert tile.crs == Projection.wgs84()
    assert tile.provider == "srtm-gl1"
    assert tile.elevation.ndim == 2


def test_should_raise_when_cache_is_empty_and_network_is_unreachable(
    fixture_bbox: GeoBounds,
    tmp_path: Path,
    stage_context: StageContext,
) -> None:
    empty_cache = tmp_path / "empty_cache"
    empty_cache.mkdir()
    source = SRTMDEMSource(
        cache_directory=empty_cache,
        base_url="http://does-not-resolve.invalid/",
        tile_side_samples=FIXTURE_TILE_SIDE_SAMPLES,
    )

    with pytest.raises(SRTMTileNotFoundError):
        source.fetch(fixture_bbox, stage_context)
