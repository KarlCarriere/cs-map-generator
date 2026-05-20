"""Condition terrain: hydrological pit-fill on the prepared float elevation.

Runs BEFORE any water-flow-based step and BEFORE quantisation, because:
- Pit-filling on uint16 quantised heightmaps loses precision (a 1-bit difference is ~1.5 cm
  at the default 1024 m scale — depressions smaller than that vanish into round-off).
- Down-stream stages that ever care about flow direction (river carving augmentation in
  v0.3+, drainage analysis) need a hydrologically conditioned DEM, not the raw one.

Algorithm: Planchon-Darboux / Wang & Liu via `pysheds`. We default to `fill_pits` (cheap,
single-cell pits) followed by `fill_depressions` (multi-cell basins). Both leave the rest of the
elevation field untouched — they are conservative ascending floods.

Determinism: pysheds operates on numpy arrays; the algorithms are deterministic for a fixed
input array and fixed library version. The version pin is enforced in `pyproject.toml` and
documented in `docs/adr/0005-water-mask-and-carving.md`.

Why pysheds and not a hand-rolled NumPy implementation:
- Numba-accelerated; orders of magnitude faster than a pure-Python pit fill at 4096×4096.
- The Planchon-Darboux algorithm is subtle (priority queue with tie-breaking) and getting it
  wrong introduces flat spurious basins. Borrowing a reviewed implementation is the right call.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.prepare_terrain import (
    PrepareTerrainResult,
    PreparedTerrain,
)
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.water import WaterFeatures

CONDITION_FILL_NODATA = np.float32(-9999.0)
"""Sentinel pushed into nodata pixels before pysheds runs.

pysheds treats `nodata` cells as walls. We swap to a very low sentinel so the surrounding
real terrain does not flood into nodata gaps. After pit-filling we mask the sentinel back to
NaN-equivalent (the nodata_mask is preserved separately on PreparedTerrain).
"""


@dataclass(frozen=True, slots=True)
class ConditionTerrainResult:
    prepared_terrain: PreparedTerrain
    road_network: RoadNetwork
    water_features: WaterFeatures


class ConditionTerrainStage:
    """Hydrologically condition the prepared elevation array.

    The stage produces a new `PreparedTerrain` whose `elevation` has had single-cell pits and
    multi-cell depressions filled. `nodata_mask`, `transform`, and the relief-range fields are
    carried through unchanged — pit filling only raises low cells, it does not change the
    overall min/max relief range in any meaningful way for a normal DEM.
    """

    name = "condition_terrain"

    def __init__(
        self,
        *,
        fill_single_cell_pits: bool = True,
        fill_multi_cell_depressions: bool = True,
    ) -> None:
        # Both knobs are kept explicit so a future stage that wants ONLY pit-fill (e.g. for a
        # debug path that compares the two stages) can disable depression filling without
        # forking the stage class.
        self._fill_single_cell_pits = fill_single_cell_pits
        self._fill_multi_cell_depressions = fill_multi_cell_depressions

    def run(
        self,
        inputs: PrepareTerrainResult,
        context: StageContext,
    ) -> ConditionTerrainResult:
        prepared = inputs.prepared_terrain
        conditioned_elevation = self._condition(
            prepared.elevation, prepared.nodata_mask, prepared.transform, context
        )
        conditioned = replace(prepared, elevation=conditioned_elevation)
        return ConditionTerrainResult(
            prepared_terrain=conditioned,
            road_network=inputs.road_network,
            water_features=inputs.water_features,
        )

    def _condition(
        self,
        elevation: NDArray[np.float32],
        nodata_mask: NDArray[np.bool_],
        transform: tuple[float, float, float, float, float, float],
        context: StageContext,
    ) -> NDArray[np.float32]:
        # Local import — pysheds pulls in numba and a hefty stack; tests that inject a fake
        # pipeline should not pay that cost.
        from affine import Affine  # noqa: PLC0415
        from pysheds.grid import Grid  # noqa: PLC0415
        from pysheds.sview import Raster, ViewFinder  # noqa: PLC0415

        # Hide nodata cells by pushing them to a low sentinel — the priority-queue flood inside
        # pysheds otherwise treats nodata as walls of `nan`, which floods into adjacent real
        # terrain unpredictably. The sentinel value never appears in real DEMs (SRTM uses
        # int16, so the lowest representable real elevation is -32767 m, far above this).
        prepared_elevation = elevation.copy()
        prepared_elevation[nodata_mask] = CONDITION_FILL_NODATA

        affine = Affine(*transform)
        viewfinder = ViewFinder(
            affine=affine,
            shape=prepared_elevation.shape,
            nodata=float(CONDITION_FILL_NODATA),
        )
        dem = Raster(prepared_elevation, viewfinder=viewfinder)
        grid = Grid.from_raster(dem)

        current: object = dem
        if self._fill_single_cell_pits:
            current = grid.fill_pits(current)
        if self._fill_multi_cell_depressions:
            current = grid.fill_depressions(current)

        result = np.asarray(current, dtype=np.float32)
        # Restore the sentinel positions to the sentinel value — they were never real terrain
        # and downstream stages dispatch on `nodata_mask`, not on the values themselves. Doing
        # this explicitly defends against pysheds' fill ever bleeding into nodata cells, which
        # would silently corrupt mask + heightmap alignment.
        result[nodata_mask] = CONDITION_FILL_NODATA

        context.logger.info(
            "terrain.conditioned",
            extra={
                "pit_fill_enabled": self._fill_single_cell_pits,
                "depression_fill_enabled": self._fill_multi_cell_depressions,
                "shape": result.shape,
            },
        )
        return result
