"""Compose stage: assemble the export-ready MapTile."""

from __future__ import annotations

from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.prepare_roads import PrepareRoadsResult
from cs_mapgen.domain.map_tile import MapTile


class ComposeMapStage:
    """Combine the prepared heightmap, road network, and water mask into a `MapTile`."""

    name = "compose_map"

    def __init__(self, target_id: str) -> None:
        if not target_id:
            raise ValueError("target_id must be a non-empty string")
        self._target_id = target_id

    def run(self, inputs: PrepareRoadsResult, context: StageContext) -> MapTile:
        return MapTile(
            heightmap=inputs.heightmap,
            road_network=inputs.road_network,
            bounds=context.bounds,
            target_id=self._target_id,
            water_mask=inputs.water_mask,
        )
