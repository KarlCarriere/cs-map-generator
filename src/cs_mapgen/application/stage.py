"""Stage Protocol and the per-run context object."""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger, getLogger
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from cs_mapgen.domain.geometry import GeoBounds, Projection

DEFAULT_SEED = 0


@dataclass(frozen=True, slots=True)
class StageContext:
    """Immutable per-run context. All side-effect dependencies (cache dir, RNG, logger) are
    passed explicitly — stages never reach for globals.

    Three related bbox fields are carried so the pipeline can stay north-up, axis-aligned in
    the working metric CRS, and produce both `heightmap.png` and `worldmap.png` for CS2:

    - `bounds`: WGS84 lat/lon envelope used to query external data providers (DEM, OSM). This
      is always a superset of the rendered area; it has to be, because lat/lon rectangles
      reproject to non-axis-aligned UTM quadrilaterals and we need full coverage after
      reprojection.
    - `target_bounds`: the exact axis-aligned rectangle (in `working_crs` coordinates) that the
      full rendered terrain covers. For CS1 this equals `playable_bounds`. For CS2 it covers
      the worldmap extent (4× linearly, 16× by area). Downstream cropping in
      `PrepareTerrainStage` and water rasterisation in `PrepareWaterStage` both key off this.
    - `playable_bounds`: the in-game playable area (working_crs). A centred subset of
      `target_bounds`. Export adapters crop to this for `heightmap.png` and `water_mask.png`;
      the surrounding region in `target_bounds` feeds `worldmap.png` for CS2.
    """

    bounds: GeoBounds
    target_bounds: GeoBounds
    playable_bounds: GeoBounds
    working_crs: Projection
    seed: int
    cache_directory: Path
    output_directory: Path
    dump_intermediates: bool = False
    logger: Logger = field(default_factory=lambda: getLogger("cs_mapgen"))

    def __post_init__(self) -> None:
        if self.target_bounds.crs.epsg != self.working_crs.epsg:
            raise ValueError(
                "target_bounds CRS must equal working_crs "
                f"(target_bounds=EPSG:{self.target_bounds.crs.epsg}, "
                f"working_crs=EPSG:{self.working_crs.epsg})"
            )
        if self.playable_bounds.crs.epsg != self.working_crs.epsg:
            raise ValueError(
                "playable_bounds CRS must equal working_crs "
                f"(playable_bounds=EPSG:{self.playable_bounds.crs.epsg}, "
                f"working_crs=EPSG:{self.working_crs.epsg})"
            )

    def rng(self) -> np.random.Generator:
        """Return a fresh NumPy generator seeded from `self.seed`.

        Each call returns an independent generator so that branches of the pipeline can draw
        without leaking state across stages. Determinism requires that the call order itself is
        deterministic; the pipeline orchestrator guarantees a fixed stage sequence.
        """
        return np.random.default_rng(self.seed)


@runtime_checkable
class Stage(Protocol):
    """A pure transformation from one typed input to one typed output.

    Implementations must be deterministic given the same inputs and context, and must not mutate
    their inputs. Any side effect (HTTP, disk I/O) is delegated to an injected port.
    """

    name: str

    def run(self, inputs: object, context: StageContext) -> object: ...
