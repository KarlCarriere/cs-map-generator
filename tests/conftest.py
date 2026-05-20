"""Shared pytest fixtures.

Determinism guard: tests must not hit the network. We do not install a global socket-block here
(which would interfere with pytest internal plumbing), but every test that exercises a port
either receives a fake collaborator or reads from a pre-populated cache fixture.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection

if TYPE_CHECKING:
    from collections.abc import Iterator

FIXTURE_TILE_SIDE_SAMPLES = 11  # tiny synthetic SRTM tile for offline tests
FIXTURE_BBOX_HALF_DEGREES = 0.05  # ~5.5 km half-side bbox centered at (0.5, 0.5)


@pytest.fixture(scope="session")
def fixture_root() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bbox() -> GeoBounds:
    # Centered at (0.5°, 0.5°) so the bbox is fully inside SRTM tile N00E000.
    center_lon = 0.5
    center_lat = 0.5
    return GeoBounds(
        west=center_lon - FIXTURE_BBOX_HALF_DEGREES,
        south=center_lat - FIXTURE_BBOX_HALF_DEGREES,
        east=center_lon + FIXTURE_BBOX_HALF_DEGREES,
        north=center_lat + FIXTURE_BBOX_HALF_DEGREES,
        crs=Projection.wgs84(),
    )


@pytest.fixture
def srtm_cache_directory(tmp_path: Path) -> Iterator[Path]:
    """Build a synthetic SRTM cache covering tiles N00E000 through S02W002 (with padding).

    The synthetic tile is a deterministic gradient — small, but valid .hgt format. Using
    `tile_side_samples=FIXTURE_TILE_SIDE_SAMPLES` keeps the file size at 242 bytes per tile.
    """
    cache_dir = tmp_path / "srtm_cache"
    cache_dir.mkdir()
    needed_tile_names = (
        "N00E000.hgt",
        "N00E001.hgt",
        "N00W001.hgt",
        "N01E000.hgt",
        "N01E001.hgt",
        "N01W001.hgt",
        "S01E000.hgt",
        "S01E001.hgt",
        "S01W001.hgt",
    )
    for name in needed_tile_names:
        (cache_dir / name).write_bytes(_synthetic_hgt_bytes(FIXTURE_TILE_SIDE_SAMPLES))
    return cache_dir


@pytest.fixture
def stage_context(fixture_bbox: GeoBounds, tmp_path: Path) -> StageContext:
    # Tests that use this fixture inject `IdentityReprojector`, which leaves coordinates
    # numerically unchanged. To keep target_bounds and the (faked) reprojected DEM consistent,
    # we pin `working_crs` to WGS84 and set both `target_bounds` and `playable_bounds` to the
    # same lat/lon rectangle as `fixture_bbox` (no separate worldmap layer). Production CS2 path
    # is exercised by integration tests that exercise PyprojReprojector for real.
    return StageContext(
        bounds=fixture_bbox,
        target_bounds=fixture_bbox,
        playable_bounds=fixture_bbox,
        working_crs=Projection.wgs84(),
        seed=42,
        cache_directory=tmp_path / "cache",
        output_directory=tmp_path / "output",
        dump_intermediates=False,
        logger=logging.getLogger("cs_mapgen.tests"),
    )


def _synthetic_hgt_bytes(side: int) -> bytes:
    """Return bytes of a deterministic gradient HGT tile with `side` samples per edge."""
    elevations = np.linspace(0, 500, side * side, dtype=np.int16).reshape((side, side))
    # SRTM .hgt is big-endian int16.
    return struct.pack(f">{side * side}h", *elevations.flatten().tolist())
