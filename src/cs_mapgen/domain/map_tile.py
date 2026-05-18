"""Composed game-ready map tile — the export-stage input."""

from __future__ import annotations

from dataclasses import dataclass

from cs_mapgen.domain.geometry import GeoBounds
from cs_mapgen.domain.network import RoadNetwork
from cs_mapgen.domain.raster import Heightmap, LandUseMap, VegetationMask, WaterMask


@dataclass(frozen=True, slots=True)
class MapTile:
    """Everything the export stage needs to produce engine artifacts.

    Optional masks/maps are populated as later phases (v0.2+) land. v0.1 fills only
    `heightmap` and `road_network`.
    """

    heightmap: Heightmap
    road_network: RoadNetwork
    bounds: GeoBounds
    target_id: str
    water_mask: WaterMask | None = None
    vegetation_mask: VegetationMask | None = None
    land_use: LandUseMap | None = None

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ValueError("target_id must be a non-empty string")
