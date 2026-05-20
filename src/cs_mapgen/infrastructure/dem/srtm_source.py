"""SRTM DEM source — cache-first, public mirror on miss.

Determinism: the cache is content-addressed by tile name (SRTM tiles are immutable). Given the
same bbox the same set of tile files is read, in sorted order, producing the same in-memory
elevation array. The network path is never exercised when the cache already holds the tiles.
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import numpy as np

from cs_mapgen.application.stage import StageContext
from cs_mapgen.domain.geometry import GeoBounds, Projection
from cs_mapgen.domain.raster import DEMTile
from cs_mapgen.infrastructure.dem.tile_index import tiles_covering

if TYPE_CHECKING:
    from collections.abc import Iterable

SRTM_TILE_SIDE_SAMPLES = 3601
SRTM_TILE_DEGREES = 1.0
SRTM_NODATA = -32768.0
SRTM_RESOLUTION_METRES = 30.0
HTTP_TIMEOUT_SECONDS = 60.0
PROVIDER_ID = "srtm-gl1"
MIN_TEST_TILE_SIDE_SAMPLES = 3  # allow very small tiles for offline fixtures
ESA_STEP_ARCHIVE_SUFFIX = ".SRTMGL1.hgt.zip"  # ESA STEP wraps every .hgt in a per-tile zip


class SRTMTileNotFoundError(RuntimeError):
    """Raised when a tile is missing from cache and cannot be fetched."""


class SRTMDEMSource:
    """Fetches SRTM 1-arc-second tiles and mosaics them into a single `DEMTile`."""

    provider_id = PROVIDER_ID

    def __init__(
        self,
        cache_directory: Path,
        base_url: str,
        http_client: httpx.Client | None = None,
        tile_side_samples: int = SRTM_TILE_SIDE_SAMPLES,
    ) -> None:
        # `tile_side_samples` is parameterised so offline test fixtures can use small synthetic
        # tiles (e.g. 11×11) without the cost of committing real 26 MB hgt files. Production
        # always uses the SRTM 1-arc-second native side (3601).
        if tile_side_samples < MIN_TEST_TILE_SIDE_SAMPLES:
            raise ValueError(f"tile_side_samples must be at least {MIN_TEST_TILE_SIDE_SAMPLES}")
        self._cache_directory = cache_directory
        self._base_url = base_url.rstrip("/") + "/"
        self._http_client = http_client
        self._tile_side_samples = tile_side_samples

    def fetch(self, bounds: GeoBounds, context: StageContext) -> DEMTile:
        tile_names = tiles_covering(bounds)
        if not tile_names:
            raise ValueError("Empty bbox yields no SRTM tiles")

        local_paths = tuple(self._ensure_local(name, context) for name in tile_names)
        elevation, transform = self._mosaic(local_paths, tile_names, self._tile_side_samples)
        return DEMTile(
            elevation=elevation,
            transform=transform,
            crs=Projection.wgs84(),
            nodata=SRTM_NODATA,
            provider=PROVIDER_ID,
            resolution_metres=SRTM_RESOLUTION_METRES,
        )

    def _ensure_local(self, tile_name: str, context: StageContext) -> Path:
        cache_path = self._cache_directory / tile_name
        if cache_path.exists():
            return cache_path
        context.logger.info(
            "srtm.cache_miss",
            extra={"tile": tile_name, "cache_dir": str(self._cache_directory)},
        )
        return self._download(tile_name, cache_path, context)

    def _download(self, tile_name: str, cache_path: Path, context: StageContext) -> Path:
        # ESA STEP exposes each tile as `{stem}.SRTMGL1.hgt.zip`, never a bare `.hgt`. We fetch
        # the archive, extract the single `.hgt` member, and persist it under the bare tile name
        # so the cache layout and reader are unchanged.
        url = f"{self._base_url}{_archive_name(tile_name)}"
        client = self._http_client or httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
        owns_client = self._http_client is None
        try:
            response = client.get(url)
        except httpx.HTTPError as error:
            raise SRTMTileNotFoundError(
                f"Failed to fetch SRTM tile {tile_name} from {url}: {error}"
            ) from error
        finally:
            if owns_client:
                client.close()

        if response.status_code != httpx.codes.OK:
            raise SRTMTileNotFoundError(
                f"SRTM tile {tile_name} not available at {url} (HTTP {response.status_code})"
            )

        hgt_bytes = _extract_hgt_member(response.content, tile_name, url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(hgt_bytes)
        context.logger.info("srtm.cached", extra={"tile": tile_name})
        return cache_path

    @staticmethod
    def _mosaic(
        tile_paths: Iterable[Path],
        tile_names: tuple[str, ...],
        tile_side_samples: int,
    ) -> tuple[np.ndarray, tuple[float, float, float, float, float, float]]:
        # Parse SW corners from tile names so the mosaic placement does not depend on the order
        # of os.listdir or any other non-deterministic source.
        corners: list[tuple[int, int, Path]] = []
        for path, name in zip(tile_paths, tile_names, strict=True):
            lat_floor = _parse_latitude(name)
            lon_floor = _parse_longitude(name)
            corners.append((lat_floor, lon_floor, path))

        if not corners:
            raise ValueError("No SRTM tiles to mosaic")

        lat_min = min(corner[0] for corner in corners)
        lat_max = max(corner[0] for corner in corners) + int(SRTM_TILE_DEGREES)
        lon_min = min(corner[1] for corner in corners)
        lon_max = max(corner[1] for corner in corners) + int(SRTM_TILE_DEGREES)

        cols_per_tile = tile_side_samples
        rows_per_tile = tile_side_samples
        full_rows = (lat_max - lat_min) * (rows_per_tile - 1) + 1
        full_cols = (lon_max - lon_min) * (cols_per_tile - 1) + 1

        mosaic = np.full((full_rows, full_cols), SRTM_NODATA, dtype=np.float32)
        for lat_floor, lon_floor, path in corners:
            tile = _read_hgt(path, tile_side_samples)
            # Place the tile so that its SW corner lands at the correct mosaic offset. SRTM
            # files are stored north-first, so the top of the tile is at the *northern* edge.
            row_offset = (lat_max - (lat_floor + 1)) * (rows_per_tile - 1)
            col_offset = (lon_floor - lon_min) * (cols_per_tile - 1)
            mosaic[
                row_offset : row_offset + rows_per_tile,
                col_offset : col_offset + cols_per_tile,
            ] = tile

        pixel_size = SRTM_TILE_DEGREES / (cols_per_tile - 1)
        transform = (
            pixel_size,
            0.0,
            float(lon_min),
            0.0,
            -pixel_size,
            float(lat_max),
        )
        return mosaic, transform


def _archive_name(tile_name: str) -> str:
    stem = tile_name.removesuffix(".hgt")
    return f"{stem}{ESA_STEP_ARCHIVE_SUFFIX}"


def _extract_hgt_member(payload: bytes, tile_name: str, url: str) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = [name for name in archive.namelist() if name.endswith(".hgt")]
            if not members:
                raise SRTMTileNotFoundError(
                    f"SRTM archive at {url} contains no .hgt member for tile {tile_name}"
                )
            # ESA STEP zips always contain a single .hgt named after the tile. We pick the one
            # whose basename matches the requested tile to be robust to any future change in
            # member ordering or wrapper directories.
            target = next(
                (name for name in members if Path(name).name == tile_name),
                members[0],
            )
            return archive.read(target)
    except zipfile.BadZipFile as error:
        raise SRTMTileNotFoundError(
            f"SRTM payload at {url} for tile {tile_name} is not a valid zip archive"
        ) from error


def _parse_latitude(tile_name: str) -> int:
    prefix = tile_name[0]
    value = int(tile_name[1:3])
    return value if prefix == "N" else -value


def _parse_longitude(tile_name: str) -> int:
    prefix = tile_name[3]
    value = int(tile_name[4:7])
    return value if prefix == "E" else -value


def _read_hgt(path: Path, side_samples: int) -> np.ndarray:
    raw = path.read_bytes()
    expected_samples = side_samples * side_samples
    expected_bytes = expected_samples * 2
    if len(raw) != expected_bytes:
        raise ValueError(f"SRTM tile {path} has {len(raw)} bytes; expected {expected_bytes}")
    samples = struct.unpack(f">{expected_samples}h", raw)
    elevation = np.asarray(samples, dtype=np.float32).reshape((side_samples, side_samples))
    return elevation
