"""Ingest stage: fetch the OSM road network covering the bbox."""

from __future__ import annotations

from dataclasses import dataclass

from cs_mapgen.application.ports import OSMSource
from cs_mapgen.application.stage import StageContext
from cs_mapgen.application.stages.ingest_dem import IngestDEMResult
from cs_mapgen.domain.network import RoadNetwork

DEFAULT_NETWORK_TYPE = "drive"


@dataclass(frozen=True, slots=True)
class IngestRoadsResult:
    ingested_dem: IngestDEMResult
    road_network: RoadNetwork


class IngestRoadsStage:
    """Delegates road graph acquisition to an injected `OSMSource` port."""

    name = "ingest_roads"

    def __init__(self, osm_source: OSMSource, network_type: str = DEFAULT_NETWORK_TYPE) -> None:
        self._osm_source = osm_source
        self._network_type = network_type

    def run(self, inputs: IngestDEMResult, context: StageContext) -> IngestRoadsResult:
        network = self._osm_source.fetch_roads(context.bounds, self._network_type, context)
        return IngestRoadsResult(ingested_dem=inputs, road_network=network)
