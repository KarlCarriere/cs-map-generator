"""Quantise the prepared+conditioned float terrain into the final uint16 `Heightmap`.

This is the third (and final) terrain stage in the v0.2 pipeline:

    PrepareTerrainStage   -> reproject + resample to target grid (float32)
    ConditionTerrainStage -> pysheds pit-fill (float32)
    PrepareWaterStage     -> rasterise water onto the same grid (WaterMask)
   *QuantizeHeightmapStage* -> CARVE under WaterMask, linear stretch, quantise to uint16

Carving rule (documented in ADR 0005):

For every pixel where `water_mask.mask == True`, the heightmap pixel's elevation is clamped to
just below `sea_level_metres` so the in-game water plane covers it cleanly. We clamp at
`sea_level_metres - epsilon` where epsilon is one uint16 quantisation step (`height_scale /
65535`). Going lower would punch unnecessary holes; clamping exactly at sea level can leave the
water plane Z-fighting with the terrain on some GPUs.

Why carving on the float array (not the uint16 array): we want the post-carve elevation to map
cleanly through the linear-stretch normalisation. Carving in uint16 space requires the
stretch parameters to already match the float relief; staying in float lets the stretch absorb
the carve and produce a single-pass result.

Determinism: pure NumPy. No RNG, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.prepare_water import PrepareWaterResult
from cs_mapgen.domain.geometry import GeoBounds
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.raster import HEIGHTMAP_UINT16_DTYPE, Heightmap
from cs_mapgen.domain.water import WaterMask

UINT16_MAX_VALUE = 65535
# Small offset below sea level so the in-game water plane sits above the carved terrain rather
# than at exact equality (which causes Z-fighting on some GPUs). One uint16 step at the default
# 1024 m scale is ~1.56 cm — invisible to the player, robust to GPU precision quirks.
SEA_LEVEL_EPSILON_QUANTISATION_STEPS = 1.0


@dataclass(frozen=True, slots=True)
class QuantizeHeightmapResult:
    heightmap: Heightmap
    road_network: RoadNetwork
    water_mask: WaterMask


class QuantizeHeightmapStage:
    """Carve under water mask, linearly stretch to `[0, height_scale]`, quantise to uint16."""

    name = "quantize_heightmap"

    def run(
        self,
        inputs: PrepareWaterResult,
        context: StageContext,
    ) -> QuantizeHeightmapResult:
        prepared = inputs.prepared_terrain
        water_mask = inputs.water_mask

        elevation = prepared.elevation.copy()
        nodata = prepared.nodata_mask

        # Determine sea-level value in the same float units the elevation array uses. We assume
        # the float elevation is in **metres above mean sea level**, which is true for SRTM and
        # most public DEMs. If a future DEM provider uses a non-MSL datum the carve will be
        # offset by that datum — ADR 0005 calls this out and tracks it.
        if water_mask.shape != elevation.shape:
            raise ValueError(
                f"Water mask shape {water_mask.shape} does not match elevation "
                f"shape {elevation.shape}; alignment was lost between prepare_water and "
                f"quantize_heightmap"
            )

        height_scale = prepared.height_scale_metres
        sea_level = prepared.sea_level_metres
        quantisation_step_metres = height_scale / UINT16_MAX_VALUE
        carve_target_metres = (
            sea_level - quantisation_step_metres * SEA_LEVEL_EPSILON_QUANTISATION_STEPS
        )

        # Carve: any cell flagged as water is forced to `carve_target_metres`, but only if its
        # current elevation is ABOVE that target. Cells already below sea level (e.g. a Dutch
        # polder where DEM elevation is naturally < 0 m) are left alone — over-carving would
        # erase real bathymetry detail without benefit.
        water_and_above_sea = water_mask.mask & (elevation > carve_target_metres) & ~nodata
        elevation[water_and_above_sea] = carve_target_metres

        # Linear stretch into [0, height_scale]. For targets with a wider rendered extent than
        # playable area (CS2 worldmap, render_extent_multiplier > 1), the min/max range used
        # for the stretch comes from the PLAYABLE region only — otherwise distant high points
        # in the worldmap (e.g. mountains beyond the play area) would crush the playable area's
        # elevation range into a narrow grayscale band. Pixels in the surrounding worldmap that
        # fall outside the playable range simply clip to 0 or 65535 in the output PNG.
        valid_mask = ~nodata
        if not bool(valid_mask.any()):
            raise ValueError(
                "All elevation pixels are nodata at quantise time — should never happen "
                "after prepare_terrain validated non-empty coverage"
            )

        playable_window = _playable_pixel_window(
            transform=prepared.transform,
            shape=elevation.shape,
            target_bounds=context.target_bounds,
            playable_bounds=context.playable_bounds,
        )
        normalised, valid_min, valid_max = _linear_stretch(
            elevation,
            valid_mask,
            height_scale,
            sea_level,
            stretch_window=playable_window,
        )

        # Clip + quantise. We compress (rather than clip) when relief overshoots height_scale;
        # the warning was already emitted by prepare_terrain on the original relief.
        quantised = np.round(np.clip(normalised, 0.0, 1.0) * UINT16_MAX_VALUE).astype(
            HEIGHTMAP_UINT16_DTYPE
        )

        heightmap = Heightmap(
            pixels=quantised,
            width=quantised.shape[1],
            height=quantised.shape[0],
            height_scale_metres=height_scale,
            sea_level_metres=sea_level,
            bounds=context.bounds,
        )
        context.logger.info(
            "heightmap.quantised",
            extra={
                "valid_min_metres": valid_min,
                "valid_max_metres": valid_max,
                "water_pixels": int(water_mask.mask.sum()),
            },
        )

        return QuantizeHeightmapResult(
            heightmap=heightmap,
            road_network=inputs.road_network,
            water_mask=water_mask,
        )


def _linear_stretch(
    elevation: NDArray[np.float32],
    valid_mask: NDArray[np.bool_],
    height_scale_metres: float,
    sea_level_metres: float,
    stretch_window: tuple[int, int, int, int] | None = None,
) -> tuple[NDArray[np.float32], float, float]:
    # `height_scale_metres` / `sea_level_metres` are recorded on the Heightmap value object but
    # do NOT participate in the stretch math here — that is intentional and matches v0.1
    # behaviour exactly. We map a chosen relief range into the uint16 [0, 1] range; the
    # engine-side slider (CS1/CS2 Map Editor) interprets uint16 1.0 as `height_scale_metres`.
    #
    # `stretch_window`, when supplied as `(row_start, row_end, col_start, col_end)`, restricts
    # the min/max derivation to that pixel window (the playable region). Pixels outside the
    # window still get stretched using the same parameters and may clip — the heightmap PNG
    # only needs full dynamic range INSIDE the playable area.
    del height_scale_metres, sea_level_metres
    if stretch_window is None:
        sample_elevation = elevation
        sample_valid = valid_mask
    else:
        row_start, row_end, col_start, col_end = stretch_window
        sample_elevation = elevation[row_start:row_end, col_start:col_end]
        sample_valid = valid_mask[row_start:row_end, col_start:col_end]
        if not bool(sample_valid.any()):
            # Fall back to the full array if the playable window happens to be all nodata.
            sample_elevation = elevation
            sample_valid = valid_mask
    valid_min = float(sample_elevation[sample_valid].min())
    valid_max = float(sample_elevation[sample_valid].max())
    relief = valid_max - valid_min
    if relief <= 0.0:
        # Flat DEM — return mid-grey so the resulting uint16 has a valid value everywhere.
        return (np.full_like(elevation, 0.5, dtype=np.float32), valid_min, valid_max)

    stretched = np.where(
        valid_mask,
        (elevation - valid_min) / relief,
        0.0,
    ).astype(np.float32)
    return stretched, valid_min, valid_max


def _playable_pixel_window(
    *,
    transform: tuple[float, float, float, float, float, float],
    shape: tuple[int, int],
    target_bounds: GeoBounds,
    playable_bounds: GeoBounds,
) -> tuple[int, int, int, int]:
    """Return `(row_start, row_end, col_start, col_end)` for the playable region.

    `transform` is the rasterio-style affine `(a, b, c, d, e, f)` of the rendered raster,
    where the raster spans `target_bounds`. If `playable_bounds == target_bounds` (CS1) this
    returns the full window.
    """
    pixel_width, b, west_origin, d, pixel_height, north_origin = transform
    del b, d, target_bounds  # transform + shape are authoritative for the raster's pixel grid
    rows, cols = shape
    col_start = max(0, int(np.floor((playable_bounds.west - west_origin) / pixel_width)))
    col_end = min(cols, int(np.ceil((playable_bounds.east - west_origin) / pixel_width)))
    # `pixel_height` is negative (rasterio convention: y decreases as row increases).
    row_start = max(0, int(np.floor((playable_bounds.north - north_origin) / pixel_height)))
    row_end = min(rows, int(np.ceil((playable_bounds.south - north_origin) / pixel_height)))
    return row_start, row_end, col_start, col_end
