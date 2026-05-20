"""Quantise the prepared+conditioned float terrain into the final uint16 `Heightmap`.

This is the third (and final) terrain stage in the v0.2 pipeline:

    PrepareTerrainStage   -> reproject + resample to target grid (float32)
    ConditionTerrainStage -> pysheds pit-fill (float32)
    PrepareWaterStage     -> rasterise water onto the same grid (WaterMask)
   *QuantizeHeightmapStage* -> CARVE under WaterMask, linear stretch, quantise to uint16

Carving rule (amends ADR 0005 §1):

For every pixel where `water_mask.mask == True` AND the pixel's elevation is currently above
the carve target, the elevation is clamped to `sea_level_metres - water_carve_depth_metres`.
The default depth is 5 m (was "one uint16 quantisation step" ≈ 1.56 cm at the original
spec — too tight, because the in-editor water-level slider has to land within that interval
or every river drains). 5 m gives a comfortable slider margin AND gives rivers a realistic
bed depth instead of being infinitely thin sheets right at the surface. Pixels already below
the carve target (Dutch polders, natural bathymetry) are left alone — over-carving would
erase real elevation detail without benefit. A floor of one quantisation step ensures we
never carve LESS than the Z-fight margin.

Why carving on the float array (not the uint16 array): we want the post-carve elevation to map
cleanly through the absolute encoding. Carving in uint16 space requires the
encoding parameters to already match the float relief; staying in float lets the encoding
absorb the carve and produce a single-pass result.

Determinism: pure NumPy. No RNG, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.prepare_water import PrepareWaterResult
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.raster import HEIGHTMAP_UINT16_DTYPE, Heightmap
from cs_mapgen.domain.water import WaterMask

UINT16_MAX_VALUE = 65535
# How far BELOW sea level water cells are carved. The original ADR 0005 spec was
# "one uint16 quantisation step" (~1.56 cm at the default 1024 m scale) — just enough to dodge
# Z-fighting between the engine water plane and the carved terrain. That tolerance is too tight
# for in-editor use: any small nudge to the CS2 water-level slider drains every river. We now
# carve to a configurable depth (default 5 m) so the user can tweak the water level by a few
# metres without losing the rivers, and rivers gain a realistic bed depth instead of being
# infinitely thin.
DEFAULT_WATER_CARVE_DEPTH_METRES = 100.0
# Floor on the carve depth in quantised-step units — never carve LESS than one step below sea
# level (Z-fight protection). The user's configured depth is `max(configured, this_floor)`.
MIN_WATER_CARVE_QUANTISATION_STEPS = 1.0


@dataclass(frozen=True, slots=True)
class QuantizeHeightmapResult:
    heightmap: Heightmap
    road_network: RoadNetwork
    water_mask: WaterMask


class QuantizeHeightmapStage:
    """Carve under water mask, encode elevation as absolute metres, quantise to uint16.

    `water_carve_depth_metres` is how far below `sea_level_metres` water cells are clamped. The
    default 5 m gives the user a comfortable margin to nudge CS2's water-level slider before
    rivers start draining or land starts flooding. Pass `0.0` to fall back to the historical
    "one uint16 step" carve (rivers will look razor-thin and disappear on the slightest slider
    move).
    """

    name = "quantize_heightmap"

    def __init__(
        self,
        water_carve_depth_metres: float = DEFAULT_WATER_CARVE_DEPTH_METRES,
    ) -> None:
        if water_carve_depth_metres < 0.0:
            raise ValueError(
                f"water_carve_depth_metres must be >= 0, got {water_carve_depth_metres}"
            )
        self._water_carve_depth_metres = water_carve_depth_metres

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
        min_carve_depth_metres = quantisation_step_metres * MIN_WATER_CARVE_QUANTISATION_STEPS
        carve_depth_metres = max(self._water_carve_depth_metres, min_carve_depth_metres)
        carve_target_metres = sea_level - carve_depth_metres

        # Carve: any cell flagged as water is forced to `carve_target_metres`, but only if its
        # current elevation is ABOVE that target. Cells already below sea level (e.g. a Dutch
        # polder where DEM elevation is naturally < 0 m) are left alone — over-carving would
        # erase real bathymetry detail without benefit.
        water_and_above_sea = water_mask.mask & (elevation > carve_target_metres) & ~nodata
        elevation[water_and_above_sea] = carve_target_metres

        # Absolute encoding: uint16 0 ↔ 0 m, uint16 65535 ↔ `height_scale_metres`. Real-world
        # elevations are preserved 1:1, so a 300 m hill stays 300 m in-game (CS2's Map Editor
        # interprets uint16 1.0 as `height_scale_metres`). Anything above `height_scale_metres`
        # clips to 65535 — `prepare_terrain` already emits a `relief_exceeds_height_scale`
        # warning when that happens. Pre-stretch behaviour scaled the playable range to fill
        # the uint16 codomain, which silently inflated all elevations by `height_scale / relief`
        # — typical 3-4× vertical exaggeration in flat-to-medium areas.
        valid_mask = ~nodata
        if not bool(valid_mask.any()):
            raise ValueError(
                "All elevation pixels are nodata at quantise time — should never happen "
                "after prepare_terrain validated non-empty coverage"
            )

        normalised, valid_min, valid_max = _absolute_encode(
            elevation,
            valid_mask,
            height_scale,
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


def _absolute_encode(
    elevation: NDArray[np.float32],
    valid_mask: NDArray[np.bool_],
    height_scale_metres: float,
) -> tuple[NDArray[np.float32], float, float]:
    """Encode elevation as `value = elevation / height_scale_metres`, clipped to [0, 1].

    Pre-clip min / max are returned for logging — they give the diagnostic "if your hills were
    cut off, look at this number" without having to scan the array again downstream.
    """
    if height_scale_metres <= 0.0:
        raise ValueError(f"height_scale_metres must be > 0, got {height_scale_metres}")
    valid_min = float(elevation[valid_mask].min())
    valid_max = float(elevation[valid_mask].max())
    encoded = np.where(valid_mask, elevation / height_scale_metres, 0.0)
    return np.clip(encoded, 0.0, 1.0).astype(np.float32), valid_min, valid_max
