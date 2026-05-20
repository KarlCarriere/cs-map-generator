"""Prepare terrain: reproject DEM to working CRS and resample to the target heightmap grid.

This is the first half of what used to be a monolithic prepare-then-quantize stage in v0.1. The
split was introduced in v0.2 so hydrological conditioning (`ConditionTerrainStage`) and water
carving (`QuantizeHeightmapStage`) can run on the **float, working-CRS, target-resolution**
elevation array before it is normalised and quantised to uint16.

Inputs CRS: whatever the DEM source delivers (typically EPSG:4326 for SRTM).
Output CRS: `context.working_crs`.

Output shape: `(target_side_pixels, target_side_pixels)` exactly. The downstream water mask is
rasterised on this same grid, so the export target sees raster/mask alignment for free.

Resampling choice: bilinear. Cubic overshoots on steep slopes and can introduce negative
elevations near coastlines; bilinear is the safer default for continuous-field DEMs.

Determinism: reprojection is delegated to `Reprojector.reproject_raster`. GDAL/PROJ is bitwise
deterministic for fixed input grids; the placeholder identity-reprojector path is integer index
math. Either way: same input → same float array.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cs_mapgen.application.ports import Reprojector
from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.ingest_water import IngestWaterResult
from cs_mapgen.domain.geometry import GeoBounds
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.water import WaterFeatures

DEFAULT_HEIGHTMAP_SIDE_PIXELS = 1081
DEFAULT_HEIGHT_SCALE_METRES = 1024.0
DEFAULT_SEA_LEVEL_METRES = 40.0
MIN_HEIGHTMAP_SIDE_PIXELS = 32
BILINEAR_RESAMPLING = "bilinear"


@dataclass(frozen=True, slots=True)
class PreparedTerrain:
    """Float-precision elevation on the working CRS, target heightmap grid, pre-quantisation.

    `elevation` is `float32` on a `(side, side)` grid. `nodata_mask` is `True` where the source
    DEM was missing (so downstream stages know not to treat that pixel's elevation as real).
    `transform` is the 6-tuple affine in `crs`. `relief_min_metres` / `relief_max_metres` carry
    the input elevation range for the eventual normalise step — passing them through avoids a
    second scan after pit-filling shifts values.
    """

    elevation: NDArray[np.float32]
    nodata_mask: NDArray[np.bool_]
    transform: tuple[float, float, float, float, float, float]
    relief_min_metres: float
    relief_max_metres: float
    height_scale_metres: float
    sea_level_metres: float


@dataclass(frozen=True, slots=True)
class PrepareTerrainResult:
    """Carries the prepared float terrain plus the road network and raw water features forward.

    Threading raw water features through here (rather than fetching them again later) keeps the
    stage ordering linear and lets the prepare-water stage see exactly what was ingested without
    a sideways port lookup.
    """

    prepared_terrain: PreparedTerrain
    road_network: RoadNetwork
    water_features: WaterFeatures


class PrepareTerrainStage:
    """Reproject + resample the DEM to a `(side, side)` float grid in the working CRS.

    Known limitations: when real relief exceeds `height_scale_metres` (e.g. Alps), the resulting
    `Heightmap` produced by `QuantizeHeightmapStage` will clip. Compression strategy is deferred
    to v0.4 — we surface a warning here so the issue is observable in the logs.
    """

    name = "prepare_terrain"

    def __init__(
        self,
        reprojector: Reprojector,
        target_side_pixels: int = DEFAULT_HEIGHTMAP_SIDE_PIXELS,
        height_scale_metres: float = DEFAULT_HEIGHT_SCALE_METRES,
        sea_level_metres: float = DEFAULT_SEA_LEVEL_METRES,
    ) -> None:
        if target_side_pixels < MIN_HEIGHTMAP_SIDE_PIXELS:
            raise ValueError(f"target_side_pixels must be at least {MIN_HEIGHTMAP_SIDE_PIXELS}")
        self._reprojector = reprojector
        self._target_side_pixels = target_side_pixels
        self._height_scale_metres = height_scale_metres
        self._sea_level_metres = sea_level_metres

    def run(self, inputs: IngestWaterResult, context: StageContext) -> PrepareTerrainResult:
        reprojected = self._reprojector.reproject_raster(
            inputs.ingested_roads.ingested_dem.dem_tile,
            context.working_crs,
            BILINEAR_RESAMPLING,
        )

        cropped_elevation, cropped_valid_mask, cropped_transform = _crop_to_target_bounds(
            elevation=reprojected.elevation,
            transform=reprojected.transform,
            nodata=reprojected.nodata,
            target_bounds=context.target_bounds,
        )

        if not bool(cropped_valid_mask.any()):
            raise ValueError(
                "All DEM samples are nodata after reprojection and cropping — "
                "target_bounds may lie outside DEM coverage"
            )

        valid_min = float(cropped_elevation[cropped_valid_mask].min())
        valid_max = float(cropped_elevation[cropped_valid_mask].max())
        if valid_max - valid_min > self._height_scale_metres:
            context.logger.warning(
                "terrain.relief_exceeds_height_scale",
                extra={
                    "relief": valid_max - valid_min,
                    "ceiling": self._height_scale_metres,
                },
            )

        resampled_elevation, resampled_nodata, resampled_transform = self._resample_to_side(
            cropped_elevation,
            cropped_valid_mask,
            cropped_transform,
            self._target_side_pixels,
        )

        prepared = PreparedTerrain(
            elevation=resampled_elevation,
            nodata_mask=resampled_nodata,
            transform=resampled_transform,
            relief_min_metres=valid_min,
            relief_max_metres=valid_max,
            height_scale_metres=self._height_scale_metres,
            sea_level_metres=self._sea_level_metres,
        )
        return PrepareTerrainResult(
            prepared_terrain=prepared,
            road_network=inputs.ingested_roads.road_network,
            water_features=inputs.water_features,
        )

    @staticmethod
    def _resample_to_side(
        elevation: NDArray[np.float32],
        valid_mask: NDArray[np.bool_],
        source_transform: tuple[float, float, float, float, float, float],
        target_side: int,
    ) -> tuple[
        NDArray[np.float32],
        NDArray[np.bool_],
        tuple[float, float, float, float, float, float],
    ]:
        # Integer index nearest-neighbour resample — deterministic, vectorised, GDAL-free. The
        # production `Reprojector` should already deliver the working-CRS grid; this final
        # snap-to-(side, side) keeps the output shape pinned regardless of upstream grid size.
        # We carry the nodata mask along so downstream conditioning sees real holes, not zeros.
        rows, cols = elevation.shape
        row_indices = np.linspace(0, rows - 1, target_side).round().astype(np.int64)
        col_indices = np.linspace(0, cols - 1, target_side).round().astype(np.int64)
        sampled_elevation = elevation[np.ix_(row_indices, col_indices)].astype(
            np.float32, copy=True
        )
        sampled_valid = valid_mask[np.ix_(row_indices, col_indices)]
        sampled_nodata = ~sampled_valid

        # Scale the source affine to the new pixel size while preserving the upper-left origin.
        # source_transform is (a, b, c, d, e, f) → pixel size (a, e), origin (c, f). After
        # sub-sampling by index, the effective pixel size becomes (a * cols / target_side,
        # e * rows / target_side). For diagnostics and the water mask alignment this is the
        # correct affine to carry forward.
        a, b, c, d, e, f = source_transform
        scaled_transform: tuple[float, float, float, float, float, float] = (
            a * cols / target_side,
            b,
            c,
            d,
            e * rows / target_side,
            f,
        )
        return sampled_elevation, sampled_nodata, scaled_transform


def _crop_to_target_bounds(
    *,
    elevation: NDArray[np.float32],
    transform: tuple[float, float, float, float, float, float],
    nodata: float,
    target_bounds: GeoBounds,
) -> tuple[
    NDArray[np.float32],
    NDArray[np.bool_],
    tuple[float, float, float, float, float, float],
]:
    """Crop the reprojected DEM to the axis-aligned `target_bounds` rectangle.

    The reprojected DEM lives on an axis-aligned grid in `working_crs`. We compute the
    pixel window that corresponds to `target_bounds` and slice. The output is then guaranteed
    to be axis-aligned in `working_crs` — no rotation, no nodata wedges from the WGS84-to-UTM
    projection of the source bbox. This is what fixes the "crooked map" rendering.

    The slice clamps to the available pixel range. In production the resolver pads
    `fetch_bounds` so this never clips at the edges; in tests using an identity-reprojector
    the source extent may be tight and we tolerate that gracefully.
    """
    if elevation.ndim != 2:
        raise ValueError(f"elevation must be 2D, got shape {elevation.shape}")
    pixel_width, b, west_origin, d, pixel_height, north_origin = transform
    if b != 0.0 or d != 0.0:
        raise ValueError(
            "Cropping only supports axis-aligned (no-shear) source transforms. "
            f"Got b={b}, d={d}."
        )
    if pixel_width <= 0.0 or pixel_height >= 0.0:
        # rasterio convention: pixel_height is negative (y decreases downward). Refuse
        # other orientations rather than silently mis-cropping.
        raise ValueError(
            "Cropping expects positive pixel_width and negative pixel_height "
            f"(got pixel_width={pixel_width}, pixel_height={pixel_height})."
        )

    rows, cols = elevation.shape
    # Convert target_bounds to fractional pixel indices, then floor/ceil to integer rows/cols
    # that fully cover the target rectangle.
    col_start_f = (target_bounds.west - west_origin) / pixel_width
    col_end_f = (target_bounds.east - west_origin) / pixel_width
    row_start_f = (target_bounds.north - north_origin) / pixel_height  # north → smaller row
    row_end_f = (target_bounds.south - north_origin) / pixel_height

    col_start = max(0, int(np.floor(col_start_f)))
    col_end = min(cols, int(np.ceil(col_end_f)))
    row_start = max(0, int(np.floor(row_start_f)))
    row_end = min(rows, int(np.ceil(row_end_f)))

    if col_end <= col_start or row_end <= row_start:
        raise ValueError(
            "target_bounds does not overlap the reprojected DEM. "
            f"target=({target_bounds.west},{target_bounds.south})-"
            f"({target_bounds.east},{target_bounds.north}); "
            f"source pixel-window: rows[{row_start}:{row_end}], cols[{col_start}:{col_end}]"
        )

    cropped = elevation[row_start:row_end, col_start:col_end].astype(np.float32, copy=False)
    valid = np.isfinite(cropped) & (cropped != nodata)

    cropped_transform = (
        pixel_width,
        0.0,
        west_origin + col_start * pixel_width,
        0.0,
        pixel_height,
        north_origin + row_start * pixel_height,
    )
    return cropped, valid, cropped_transform
