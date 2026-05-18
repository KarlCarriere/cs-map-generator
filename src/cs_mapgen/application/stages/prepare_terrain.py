"""Prepare terrain: reproject DEM to working CRS, normalize, quantize to uint16."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cs_mapgen.application.ports import Reprojector
from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.ingest_roads import IngestRoadsResult
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.raster import HEIGHTMAP_UINT16_DTYPE, Heightmap

DEFAULT_HEIGHTMAP_SIDE_PIXELS = 1081
DEFAULT_HEIGHT_SCALE_METRES = 1024.0
DEFAULT_SEA_LEVEL_METRES = 40.0
UINT16_MAX_VALUE = 65535
BILINEAR_RESAMPLING = "bilinear"


@dataclass(frozen=True, slots=True)
class PrepareTerrainResult:
    road_network: RoadNetwork
    heightmap: Heightmap


class PrepareTerrainStage:
    """Reproject DEM into the working CRS, then linearly stretch + quantize to uint16.

    Inputs CRS: whatever the DEM source delivers (typically EPSG:4326 for SRTM).
    Output CRS: `context.working_crs`.

    Resampling choice: bilinear. Cubic overshoots on steep slopes and can introduce negative
    elevations near coastlines; bilinear is the safer default for continuous-field DEMs.

    Determinism: stretching uses fixed constants; reprojection uses GDAL/PROJ which is bitwise
    deterministic for fixed input grids.

    Known limitations: when real relief exceeds `DEFAULT_HEIGHT_SCALE_METRES` (e.g. Alps), v0.1
    clips and logs a warning. Compression strategy is deferred to v0.4.
    """

    name = "prepare_terrain"

    def __init__(
        self,
        reprojector: Reprojector,
        target_side_pixels: int = DEFAULT_HEIGHTMAP_SIDE_PIXELS,
        height_scale_metres: float = DEFAULT_HEIGHT_SCALE_METRES,
        sea_level_metres: float = DEFAULT_SEA_LEVEL_METRES,
    ) -> None:
        if target_side_pixels < 32:
            raise ValueError("target_side_pixels must be at least 32")
        self._reprojector = reprojector
        self._target_side_pixels = target_side_pixels
        self._height_scale_metres = height_scale_metres
        self._sea_level_metres = sea_level_metres

    def run(self, inputs: IngestRoadsResult, context: StageContext) -> PrepareTerrainResult:
        reprojected = self._reprojector.reproject_raster(
            inputs.ingested_dem.dem_tile,
            context.working_crs,
            BILINEAR_RESAMPLING,
        )

        elevation = reprojected.elevation
        # Build a mask of valid samples without leaking nodata into arithmetic.
        nodata_value = reprojected.nodata
        valid_mask = np.isfinite(elevation) & (elevation != nodata_value)
        if not bool(valid_mask.any()):
            raise ValueError(
                "All DEM samples are nodata after reprojection — bbox may lie outside coverage"
            )

        valid_min = float(elevation[valid_mask].min())
        valid_max = float(elevation[valid_mask].max())
        if valid_max - valid_min > self._height_scale_metres:
            context.logger.warning(
                "terrain.relief_exceeds_height_scale",
                extra={
                    "relief": valid_max - valid_min,
                    "ceiling": self._height_scale_metres,
                },
            )

        normalized = self._linear_stretch_uint16(elevation, valid_mask, valid_min, valid_max)
        downsampled = self._resample_to_side(normalized, self._target_side_pixels)

        heightmap = Heightmap(
            pixels=downsampled,
            width=self._target_side_pixels,
            height=self._target_side_pixels,
            height_scale_metres=self._height_scale_metres,
            sea_level_metres=self._sea_level_metres,
            bounds=context.bounds,
        )
        return PrepareTerrainResult(
            road_network=inputs.road_network,
            heightmap=heightmap,
        )

    @staticmethod
    def _linear_stretch_uint16(
        elevation: np.ndarray,
        valid_mask: np.ndarray,
        valid_min: float,
        valid_max: float,
    ) -> np.ndarray:
        denom = valid_max - valid_min
        if denom == 0:
            # Flat DEM — emit mid-grey rather than divide by zero.
            return np.full(elevation.shape, UINT16_MAX_VALUE // 2, dtype=HEIGHTMAP_UINT16_DTYPE)
        stretched = np.where(
            valid_mask,
            (elevation - valid_min) / denom,
            0.0,
        )
        return np.round(np.clip(stretched, 0.0, 1.0) * UINT16_MAX_VALUE).astype(
            HEIGHTMAP_UINT16_DTYPE
        )

    @staticmethod
    def _resample_to_side(image: np.ndarray, target_side: int) -> np.ndarray:
        """Nearest-neighbor downsample for the placeholder path; a proper export-stage call to
        `rasterio.warp.reproject` will replace this when the infrastructure adapter is wired.

        This block is deterministic by construction (integer index math).
        """
        rows, cols = image.shape
        row_indices = np.linspace(0, rows - 1, target_side).round().astype(np.int64)
        col_indices = np.linspace(0, cols - 1, target_side).round().astype(np.int64)
        sampled = image[np.ix_(row_indices, col_indices)]
        return sampled.astype(HEIGHTMAP_UINT16_DTYPE, copy=False)
